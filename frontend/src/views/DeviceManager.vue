<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch, inject } from 'vue'
import {
  Camera,
  Cellphone,
  Refresh,
  Loading,
  Fold,
  Document,
  Monitor,
  Search,
  Picture,
  Delete,
  Back,
  HomeFilled,
  Grid,
  ZoomIn,
  ZoomOut,
  FolderOpened,
  ArrowDown,
  ArrowRight,
  CircleCheck,
  WarningFilled,
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  captureDeviceScreenshot,
  clickDeviceTemplate,
  clickDeviceText,
  connectDevice,
  getCurrentApp,
  getAssetUrl,
  imageCompare,
  captureTemplate,
  locateDeviceUiElement,
  runDeviceControlCommand,
  swipeDevice,
  tapDevicePoint,
  type DeviceInfo,
  type ImageCompareResponse,
  type DeviceUiLocateResponse,
  type FileTreeItem,
  type ScreenshotResponse,
} from '../api'
import { useDeviceStore, useScriptStore } from '../stores'
import { useKeyboardShortcuts, useScriptTerminal, type ScreenStreamHandle } from '../composables'
import { usePolling } from '../composables'
import {
  classifyMobileGesture,
  normalizedGestureDuration,
  shouldStartLiveTouch,
  shouldUseContinuousTouch,
  TAP_DISTANCE_PX,
} from '../utils/mobileGesture'
import FileTreeNode from '../components/FileTreeNode.vue'
import AutomationSidebar from '../components/device/AutomationSidebar.vue'
import AutoExecutePanel from '../components/device/AutoExecutePanel.vue'
import TerminalPanel from '../components/device/TerminalPanel.vue'

// Stores
const deviceStore = useDeviceStore()
const scriptStore = useScriptStore()

// Screen stream — shared singleton provided by App.vue
const screen = inject<ScreenStreamHandle>('screenStream')!

// Script terminal
const terminal = useScriptTerminal()

// Detect Electron mode — uses scrcpy window instead of embedded canvas
const electronAPI = typeof window !== 'undefined' ? (window as any).electronAPI : undefined
const isElectron = Boolean(electronAPI?.isElectron)
const electronScreenStreamConfig = electronAPI?.getScreenStreamConfig?.() ?? null
const preferNativeScrcpySurface = Boolean(electronScreenStreamConfig?.preferNativeScrcpySurface)
const preferH264Stream = !isElectron || electronScreenStreamConfig?.preferH264 === true

// Keyboard shortcuts
useKeyboardShortcuts([
  { key: 'r', ctrl: true, handler: () => loadDevices(), description: '刷新设备列表' },
  { key: 's', ctrl: true, handler: () => saveActiveScript(), description: '保存当前脚本' },
  { key: 'p', ctrl: true, handler: () => toggleLeftPanel('scripts'), description: '切换到脚本面板' },
  { key: 'd', ctrl: true, handler: () => toggleLeftPanel('devices'), description: '切换到设备面板' },
  { key: 'm', ctrl: true, handler: () => toggleLeftPanel('screen'), description: '切换到投屏面板' },
  { key: 'Escape', handler: () => { leftPanelOpen.value = false }, description: '关闭侧边栏' },
])

// Local UI state
const screenshotLoading = ref<string | null>(null)
const latestScreenshot = ref<ScreenshotResponse | null>(null)
const visualBusy = ref(false)
const ocrClickText = ref('')
const templateClickFile = ref<File | null>(null)
const templateThreshold = ref(0.92)
const visualRecordMode = ref<'none' | 'click' | 'swipe' | 'input'>('none')
const visualRecordInputText = ref('')
const elementRecordEnabled = ref(false)
const elementPackageName = ref('')
const elementLocateBusy = ref(false)
const autoExecutePrewarming = ref(false)
const hierarchyPrewarmed = ref(false)
const pointerStart = ref<{ x: number; y: number; at: number } | null>(null)
const screenshotPointerStart = ref<{ x: number; y: number; at: number } | null>(null)
const screenshotImageRef = ref<HTMLImageElement | null>(null)
const autoExecuteStatusText = ref('')
const pendingRecordedInputTarget = ref<{
  xpath: string
  label: string
} | null>(null)
let pendingRecordedInput = ''
let inputFlushTimer: number | null = null
let hierarchyRefreshTimer: number | null = null
let hierarchyRefreshInFlight = false
let lastHierarchyRefreshAt = 0
let lastHierarchyCacheKey = ''

const AUTOEXECUTE_HIERARCHY_CACHE_TTL_MS = 120_000
const AUTOEXECUTE_HIERARCHY_REFRESH_DELAY_MS = 700
const AUTOEXECUTE_HIERARCHY_REFRESH_MIN_INTERVAL_MS = 1_500
const LIVE_TOUCH_MOVE_INTERVAL_MS = 16

let liveTouchActive = false
let lastLiveTouchMoveAt = 0

// AutoExecute state
const autoExecuteRecording = ref(false)
const autoExecutePlaying = ref(false)
const autoExecutePackageName = ref('')

// VSCode-style sidebar
const leftPanelOpen = ref(true)
const activeLeftTab = ref('scripts')
const openScriptTabs = ref<{ path: string; name: string; dirty: boolean; content: string }[]>([])
const activeScriptPath = ref<string | null>(null)
const activeScriptContent = ref<string | null>(null)
const expandedFolders = ref<Set<string>>(new Set())

// Automation tab state
type AutomationAssertType = 'element_exists' | 'text_visible' | 'ocr_contains' | 'image_exists' | 'app_foreground'

const assertType = ref<AutomationAssertType>('text_visible')
const assertTargetText = ref('')
const assertTargetResourceId = ref('')
const assertTargetAppId = ref('')
const assertImageThreshold = ref(0.9)
const assertImageTemplateName = ref('')
const imageCompareBusy = ref(false)
const imageCompareResult = ref<ImageCompareResponse | null>(null)

// Root-level inline creation (VSCode-style)
const rootCreating = ref(false)
const rootCreateType = ref<'file' | 'folder'>('file')
const rootCreateName = ref('')
const rootCreateInput = ref<HTMLInputElement>()

function startRootCreate(type: 'file' | 'folder') {
  rootCreateType.value = type
  rootCreateName.value = ''
  rootCreating.value = true
  nextTick(() => rootCreateInput.value?.focus())
}

async function confirmRootCreate() {
  const name = rootCreateName.value.trim()
  if (!name) { rootCreating.value = false; return }
  try {
    if (rootCreateType.value === 'folder') {
      await scriptStore.createNewFolder(name)
    } else {
      const scriptName = name.endsWith('.py') ? name : `${name}.py`
      await scriptStore.createScript(scriptName, '')
    }
    rootCreating.value = false
    ElMessage.success(rootCreateType.value === 'folder' ? '文件夹已创建' : '脚本已创建')
  } catch (e: any) {
    ElMessage.error(e.message || '创建失败')
  }
}

// Editor settings (VSCode-style)
const editorFontSize = ref(14)
const editorLineNumbers = ref(true)
const editorWordWrap = ref(false)
const editorMinimap = ref(false)

// Remote device connection
const connectDialogVisible = ref(false)
const connectAddress = ref('')

const activeScriptDirty = computed(() => {
  const tab = openScriptTabs.value.find(t => t.path === activeScriptPath.value)
  return tab?.dirty ?? false
})

const sidebarTitle = computed(() => {
  if (activeLeftTab.value === 'scripts') return '脚本'
  if (activeLeftTab.value === 'devices') return '设备'
  if (activeLeftTab.value === 'automation') return '自动化'
  return '投屏'
})

const screenModeLabel = computed(() => {
  if (!deviceStore.activeDevice) return '未连接'
  if (screen.state.value.isLoading) return '连接中'
  if (deviceStore.activeDevice.platform === 'ios') return latestScreenshot.value ? '截图模式' : '待截图'
  return screen.state.value.isConnected ? '已连接' : '未连接'
})

const screenModeTagType = computed(() => {
  if (!deviceStore.activeDevice) return 'info'
  if (screen.state.value.isLoading) return 'warning'
  if (deviceStore.activeDevice.platform === 'ios') return latestScreenshot.value ? 'warning' : 'info'
  return screen.state.value.isConnected ? 'success' : 'info'
})

const screenFrameLabel = computed(() => {
  if (!deviceStore.activeDevice) return ''
  if (deviceStore.activeDevice.platform === 'ios') return 'WDA screenshot'
  if (screen.state.value.mode === 'scrcpy-native') {
    return screen.state.value.isConnected ? '原生投屏' : '-'
  }
  return `${screen.state.value.fps} fps`
})

const isEmbeddedVideoStream = computed(() =>
  screen.state.value.provider === 'scrcpy-ffmpeg-fmp4' || screen.state.value.mimeType === 'video/mp4',
)
const isScrcpyWebCodecsStream = computed(() =>
  // NOTE: The backend maps 'scrcpy-webcodecs' → 'scrcpy-h264' so the
  // actual provider returned is 'scrcpy-h264'.  We intentionally do NOT
  // match 'scrcpy-h264' here because the H264CanvasDecoder (WebCodecs
  // hardware decoder) needs a real <canvas> element, not yumeHost.
  // The canvas v-else path renders H.264 correctly and has full
  // @pointerdown/@pointermove/@pointerup bindings for control.
  screen.state.value.provider === 'scrcpy-webcodecs' ||
  screen.state.value.mimeType === 'application/x-scrcpy-webcodecs',
)

const screenAspectRatio = computed(() => {
  const { width, height } = screen.state.value
  return width > 0 && height > 0 ? `${width} / ${height}` : undefined
})

const activeRunnableDevice = computed(() => {
  const device = latestDeviceSnapshot(deviceStore.activeDevice)
  return device?.status === 'online' ? device : null
})

const terminalLines = computed(() => terminal.lines.value)
const terminalRunning = computed(() => terminal.isRunning.value)
const terminalConnected = computed(() => terminal.isConnected.value)
const terminalReturnCode = computed(() => terminal.lastReturnCode.value)
const terminalDurationMs = computed(() => terminal.durationMs.value)

function handlePythonEnvChange(value: string | number) {
  scriptStore.selectPythonPath(String(value))
}

function toggleLeftPanel(tab: string) {
  if (activeLeftTab.value === tab && leftPanelOpen.value) {
    leftPanelOpen.value = false
  } else {
    activeLeftTab.value = tab
    leftPanelOpen.value = true
  }
}

function statusType(status: string) {
  if (status === 'online') return 'success'
  if (status === 'offline') return 'info'
  if (status === 'unauthorized') return 'warning'
  return 'danger'
}

function latestDeviceSnapshot(device: DeviceInfo | null | undefined) {
  if (!device) return null
  return deviceStore.devices.find(d => d.udid === device.udid) ?? device
}

function clearPendingRecordedInput() {
  if (inputFlushTimer !== null) {
    window.clearTimeout(inputFlushTimer)
    inputFlushTimer = null
  }
  pendingRecordedInput = ''
  pendingRecordedInputTarget.value = null
}

function resetDeviceScopedAutomationState() {
  clearPendingRecordedInput()
  autoExecuteRecording.value = false
  autoExecutePlaying.value = false
  elementRecordEnabled.value = false
  autoExecutePrewarming.value = false
  elementPackageName.value = ''
  autoExecuteStatusText.value = ''
  visualRecordMode.value = 'none'
  pointerStart.value = null
  screenshotPointerStart.value = null
  liveTouchActive = false
  markHierarchyCacheDirty()
}

function runnableActiveDevice() {
  const device = latestDeviceSnapshot(deviceStore.activeDevice)
  if (!device) {
    ElMessage.warning('请先选择一个设备')
    return null
  }
  if (device.status !== 'online') {
    ElMessage.warning('当前设备不在线')
    return null
  }
  return device
}

// Folder tree functions
function findFileInTree(name: string, items: FileTreeItem[]): FileTreeItem | null {
  for (const item of items) {
    if (item.type === 'file' && item.name === name) return item
    if (item.children) {
      const found = findFileInTree(name, item.children)
      if (found) return found
    }
  }
  return null
}

function toggleFolder(path: string) {
  if (expandedFolders.value.has(path)) {
    expandedFolders.value.delete(path)
  } else {
    expandedFolders.value.add(path)
  }
}

async function openScriptFile(item: { path: string; name: string }) {
  await openScript(item)
}

async function confirmDeleteFolder(path: string) {
  try {
    await ElMessageBox.confirm(`删除文件夹 "${path}"？文件夹必须为空才能删除。`, '确认', { type: 'warning' })
  } catch { return }
  const ok = await scriptStore.deleteFolderByPath(path)
  if (ok) {
    ElMessage.success('已删除文件夹')
  } else {
    ElMessage.error(scriptStore.error ?? '删除文件夹失败')
  }
}

// Device connection
function connectScreen(device: DeviceInfo | null | undefined) {
  const selected = latestDeviceSnapshot(device)
  if (!selected) return
  if (selected.status !== 'online') {
    ElMessage.warning('设备不在线，无法投屏')
    return
  }
  if (terminal.isRunning.value) {
    ElMessage.warning('脚本运行中，请先停止执行再切换设备')
    return
  }

  const switchingDevice = deviceStore.activeDevice?.udid !== selected.udid
  if (switchingDevice) {
    resetDeviceScopedAutomationState()
    latestScreenshot.value = null
  }

  if (
    deviceStore.activeDevice?.udid !== selected.udid ||
    deviceStore.activeDevice?.status !== selected.status ||
    deviceStore.activeDevice?.platform !== selected.platform
  ) {
    deviceStore.setActiveDevice(selected)
  }

  if (selected.platform !== 'android') {
    if (screen.state.value.udid) {
      screen.disconnect()
    }
    if (selected.platform === 'ios') {
      latestScreenshot.value = null
      // Start iOS screen stream via SocketIO or WebSocket
      screen.connect(selected.udid, {
        platform: 'ios',
        provider: 'ios-wda',
        maxFps: 10,
        maxSize: 720,
        useSocketio: true,
        wdaUrl: selected.wda_url ?? undefined,
        control: true,
      })
    } else {
      ElMessage.info('当前平台暂未接入实时投屏')
    }
    return
  }

  if (
    screen.state.value.udid === selected.udid &&
    (screen.state.value.isConnected || screen.state.value.isLoading)
  ) {
    return
  }

  latestScreenshot.value = null
  screen.connect(selected.udid, {
    platform: selected.platform,
    provider: preferH264Stream ? 'scrcpy-webcodecs' : 'scrcpy-ffmpeg-mjpeg',
    maxFps: 30,
    maxSize: isElectron ? 1280 : 720,
    useNativeScrcpySurface: preferNativeScrcpySurface,
    preferApiTouchControl: isElectron,
  })
}

function autoConnectActiveDevice() {
  const device = latestDeviceSnapshot(deviceStore.activeDevice)
  if (!device || device.status !== 'online') {
    if (screen.state.value.udid && (!device || device.udid === screen.state.value.udid)) {
      screen.disconnect()
    }
    return
  }
  if (
    screen.state.value.udid === device.udid &&
    (screen.state.value.isConnected || screen.state.value.isLoading)
  ) {
    return
  }
  connectScreen(device)
}

async function loadDevices() {
  await deviceStore.loadDevices(true)
  autoConnectActiveDevice()
}

// ── Touch handling ────────────────────────────────────────────────────
// When scrcpy control is connected (controlMode === 'live'), every pointer
// event is sent as a real-time touch_down / touch_move / touch_up.
// ADB swipe-on-mouseup is only used as fallback when scrcpy control is
// unavailable.

function hasLiveScrcpyControl(): boolean {
  // scrcpy native control (low-latency touch) is available when the backend
  // reports control_mode=scrcpy. However, even in ADB fallback mode the
  // WebSocket control channel works — the backend will use ADB input commands
  // instead of scrcpy control socket. So we treat *any* connected control
  // mode as "live" for the purpose of sending touch events.
  return (
    (screen.state.value.controlMode === 'live' || screen.state.value.controlMode === 'fallback') &&
    screen.state.value.controlConnected
  )
}

function isScrcpyNativeControl(): boolean {
  // True only when scrcpy's own control socket is active (lowest latency).
  return (
    screen.state.value.controlMode === 'live' &&
    screen.state.value.controlConnected
  )
}

function handlePointerDown(event: PointerEvent) {
  const point = screen.toDevicePoint(event)
  if (!point) return
  event.preventDefault()
  const target = event.currentTarget as HTMLElement
  target.focus()
  target.setPointerCapture(event.pointerId)
  pointerStart.value = { ...point, at: performance.now() }
  liveTouchActive = false
  lastLiveTouchMoveAt = 0

  // scrcpy live control: send touch_down immediately
  if (hasLiveScrcpyControl()) {
    liveTouchActive = screen.sendTouchDown(point.x, point.y)
  }
}

function handlePointerMove(event: PointerEvent) {
  const start = pointerStart.value
  if (!start) return
  const point = screen.toDevicePoint(event)
  if (!point) return
  event.preventDefault()
  const now = performance.now()
  const distance = Math.hypot(point.x - start.x, point.y - start.y)

  if (!liveTouchActive) {
    // scrcpy live control: start on any movement past the tiny dead zone
    if (hasLiveScrcpyControl()) {
      if (!shouldStartLiveTouch(distance)) return
      liveTouchActive = screen.sendTouchDown(start.x, start.y)
      if (!liveTouchActive) return
      lastLiveTouchMoveAt = 0
    } else {
      // ADB fallback: stricter gating since ADB motionevent is slow
      const duration = normalizedGestureDuration(start.at, now)
      if (!shouldStartLiveTouch(distance)) return
      if (!shouldUseContinuousTouch({ distance, durationMs: duration, pointerType: event.pointerType })) return
      liveTouchActive = screen.sendTouchDown(start.x, start.y)
      if (!liveTouchActive) return
      lastLiveTouchMoveAt = 0
    }
  }

  // 16ms throttle (~60fps max move rate)
  if (now - lastLiveTouchMoveAt < LIVE_TOUCH_MOVE_INTERVAL_MS) return
  lastLiveTouchMoveAt = now
  screen.sendTouchMove(point.x, point.y)
}

async function handlePointerUp(event: PointerEvent) {
  const start = pointerStart.value
  const end = screen.toDevicePoint(event)
  const usedLiveTouch = liveTouchActive
  liveTouchActive = false
  pointerStart.value = null
  if (!start || !end) return
  event.preventDefault()

  if (usedLiveTouch) {
    screen.sendTouchUp(end.x, end.y)
    // When scrcpy native control handled the gesture, we're done.
    // For ADB fallback touch, sendTouchUp sends touch_up via WebSocket
    // which the backend maps to motionevent UP — also done.
    if (isScrcpyNativeControl()) {
      void appendRecordedClick(end)
      scheduleAutoExecuteHierarchyRefresh('touch')
      return
    }
    // ADB fallback touch handled the gesture — still record and refresh
    void appendRecordedClick(end)
    scheduleAutoExecuteHierarchyRefresh('touch')
    return
  }

  // ── Below this point: ADB fallback path (no live control available) ──

  const distance = Math.hypot(end.x - start.x, end.y - start.y)
  const duration = normalizedGestureDuration(start.at, performance.now())
  const gesture = classifyMobileGesture({ distance, durationMs: duration })
  const visualMode = visualRecordMode.value

  if (handleVisualRecordGesture(start, end, distance, duration)) {
    if (!usedLiveTouch) {
      if (visualMode === 'swipe' && distance >= TAP_DISTANCE_PX) {
        screen.sendControl({
          type: 'swipe',
          x1: start.x,
          y1: start.y,
          x2: end.x,
          y2: end.y,
          duration_ms: duration,
        })
      } else if (distance < TAP_DISTANCE_PX) {
        screen.sendControl({ type: 'tap', x: end.x, y: end.y })
      }
    }
    scheduleAutoExecuteHierarchyRefresh(`visual:${visualRecordMode.value}`)
    return
  }

  if (gesture === 'tap') {
    if (!usedLiveTouch) {
      screen.sendControl({ type: 'tap', x: end.x, y: end.y })
    }
    void appendRecordedClick(end)
    scheduleAutoExecuteHierarchyRefresh('tap')
    return
  }

  if (gesture === 'long_press') {
    if (autoExecuteRecording.value) {
      flushRecordedInput()
      appendCommandToActiveScript(
        `adb.long_press(${Math.round(end.x)}, ${Math.round(end.y)}, ${duration})`,
      )
    }
    if (!usedLiveTouch) {
      screen.sendControl({ type: 'long_press', x: end.x, y: end.y, duration_ms: duration })
    }
    scheduleAutoExecuteHierarchyRefresh('long_press')
    return
  }

  if (gesture === 'drag') {
    const pressDuration = Math.min(200, duration - 100)
    const dragDuration = Math.max(100, duration - pressDuration)
    if (autoExecuteRecording.value) {
      flushRecordedInput()
      appendCommandToActiveScript(
        `adb.drag((${Math.round(start.x)}, ${Math.round(start.y)}), (${Math.round(end.x)}, ${Math.round(end.y)}), ${pressDuration}, ${dragDuration})`,
      )
    }
    if (!usedLiveTouch) {
      screen.sendDrag(start.x, start.y, end.x, end.y, {
        pressDurationMs: pressDuration,
        dragDurationMs: dragDuration,
      })
    }
    scheduleAutoExecuteHierarchyRefresh('drag')
    return
  }

  // swipe fallback
  if (autoExecuteRecording.value) {
    flushRecordedInput()
    appendCommandToActiveScript(
      `adb.swipe((${Math.round(start.x)}, ${Math.round(start.y)}), (${Math.round(end.x)}, ${Math.round(end.y)}), ${duration})`,
    )
  }
  if (!usedLiveTouch) {
    screen.sendControl({
      type: 'swipe',
      x1: start.x,
      y1: start.y,
      x2: end.x,
      y2: end.y,
      duration_ms: duration,
    })
  }
  scheduleAutoExecuteHierarchyRefresh('swipe')
}

function handlePointerCancel(event?: PointerEvent) {
  if (liveTouchActive) {
    const point = event ? screen.toDevicePoint(event) : null
    if (point) {
      screen.sendTouchUp(point.x, point.y)
    } else if (pointerStart.value) {
      screen.sendTouchUp(pointerStart.value.x, pointerStart.value.y)
    }
  }
  liveTouchActive = false
  pointerStart.value = null
}

function appendCommandToActiveScript(command: string) {
  if (activeScriptContent.value === null) return
  const nextContent = activeScriptContent.value.trimEnd()
  // Auto-insert a small wait between recorded steps for replay stability
  const waitLine = autoExecuteRecording.value ? 'auto_execute.wait(0.5)\n' : ''
  activeScriptContent.value = `${nextContent}${nextContent ? '\n' : ''}${waitLine}${command}\n`
  onScriptEdit()
}

function pythonStringLiteral(value: string): string {
  return JSON.stringify(value)
}

function toggleVisualRecordMode(mode: 'click' | 'swipe' | 'input') {
  if (!activeScriptPath.value || activeScriptContent.value === null) {
    ElMessage.warning('请先打开或创建一个脚本')
    return
  }
  if (!deviceStore.activeDevice) {
    ElMessage.warning('请先选择一个设备')
    return
  }
  visualRecordMode.value = visualRecordMode.value === mode ? 'none' : mode
  const label = mode === 'click' ? '坐标点击' : mode === 'swipe' ? '滑动' : '输入'
  if (visualRecordMode.value === 'none') {
    ElMessage.info('已关闭基础录制')
  } else {
    ElMessage.info(`已选择${label}，请在投屏画面上操作`)
  }
}

function appendBasicClick(x: number, y: number) {
  flushRecordedInput()
  appendCommandToActiveScript(`auto_execute.click(${Math.round(x)}, ${Math.round(y)})`)
}

function appendBasicSwipe(start: { x: number; y: number }, end: { x: number; y: number }, duration: number) {
  flushRecordedInput()
  appendCommandToActiveScript(
    `auto_execute.swipe((${Math.round(start.x)}, ${Math.round(start.y)}), (${Math.round(end.x)}, ${Math.round(end.y)}), ${duration})`,
  )
}

function handleVisualRecordGesture(
  start: { x: number; y: number },
  end: { x: number; y: number },
  distance: number,
  duration: number,
): boolean {
  if (visualRecordMode.value === 'none') return false
  if (activeScriptContent.value === null) {
    ElMessage.warning('请先打开或创建一个脚本')
    return true
  }

  if (visualRecordMode.value === 'click') {
    if (distance >= TAP_DISTANCE_PX) {
      ElMessage.warning('当前选择的是坐标点击，请轻点投屏画面')
      return true
    }
    appendBasicClick(end.x, end.y)
    ElMessage.success(`已写入坐标点击：${Math.round(end.x)}, ${Math.round(end.y)}`)
    return true
  }

  if (visualRecordMode.value === 'swipe') {
    if (distance < TAP_DISTANCE_PX) {
      ElMessage.warning('当前选择的是滑动，请在投屏画面上拖动')
      return true
    }
    appendBasicSwipe(start, end, duration)
    ElMessage.success('已写入滑动步骤')
    return true
  }

  if (visualRecordMode.value === 'input') {
    if (distance >= TAP_DISTANCE_PX) {
      ElMessage.warning('当前选择的是输入，请点击目标输入框')
      return true
    }
    const text = visualRecordInputText.value
    if (!text) {
      ElMessage.warning('请先填写输入内容')
      return true
    }
    appendBasicClick(end.x, end.y)
    appendCommandToActiveScript(`auto_execute.input(${pythonStringLiteral(text)})`)
    ElMessage.success('已写入输入步骤')
    return true
  }

  return false
}

async function locateRecordedClick(
  point: { x: number; y: number },
  options: { showError: boolean } = { showError: true },
): Promise<DeviceUiLocateResponse | null> {
  if (!deviceStore.activeDevice) return null
  const packageName = elementPackageName.value.trim()
  elementLocateBusy.value = true
  try {
    return await locateDeviceUiElement(deviceStore.activeDevice.udid, {
      x: point.x,
      y: point.y,
      platform: deviceStore.activeDevice.platform,
      package_name: packageName || null,
      strict_xpath_only: true,
      cache_ttl_ms: AUTOEXECUTE_HIERARCHY_CACHE_TTL_MS,
      wda_url: deviceStore.activeDevice.wda_url ?? null,
    })
  } catch (error) {
    if (options.showError) {
      ElMessage.warning(error instanceof Error ? `元素定位失败，未写入兜底：${error.message}` : '元素定位失败，未写入兜底')
    }
    return null
  } finally {
    elementLocateBusy.value = false
    if (autoExecuteRecording.value) {
      autoExecuteStatusText.value = '点击画面录制控件操作'
    }
  }
}

async function warmAutoExecuteHierarchyCache(options: { force?: boolean; showError?: boolean; silent?: boolean } = {}) {
  if (!deviceStore.activeDevice) return false
  if (!options.force && !autoExecuteRecording.value) return false
  const packageName = elementPackageName.value.trim()
  if (!options.silent) {
    elementLocateBusy.value = true
  }
  try {
    await locateDeviceUiElement(deviceStore.activeDevice.udid, {
      x: 1,
      y: 1,
      platform: deviceStore.activeDevice.platform,
      package_name: packageName || null,
      strict_xpath_only: true,
      cache_ttl_ms: 0,
      wda_url: deviceStore.activeDevice.wda_url ?? null,
    })
    hierarchyPrewarmed.value = true
    lastHierarchyCacheKey = currentHierarchyCacheKey()
    lastHierarchyRefreshAt = performance.now()
    return true
  } catch (error) {
    if (options.showError) {
      ElMessage.warning(error instanceof Error ? `控件树预加载失败：${error.message}` : '控件树预加载失败')
    }
    return false
  } finally {
    if (!options.silent) {
      elementLocateBusy.value = false
    }
  }
}

async function prewarmBeforeRecording() {
  if (hierarchyPrewarmed.value && lastHierarchyCacheKey === currentHierarchyCacheKey()) {
    autoExecuteStatusText.value = '控件树已预加载，可以点击录制'
    ElMessage.success('控件树已预加载，可以开始点击录制')
    return true
  }
  autoExecutePrewarming.value = true
  elementRecordEnabled.value = false
  autoExecuteStatusText.value = '控件树预热中，请稍等...'
  const ok = await warmAutoExecuteHierarchyCache({ force: true, showError: true })
  autoExecutePrewarming.value = false
  elementRecordEnabled.value = ok
  autoExecuteStatusText.value = ok ? '控件树已预加载，可以点击录制' : '预加载失败，请重新开启录制'
  if (ok) {
    ElMessage.success('控件树已预加载，可以开始点击录制')
  } else {
    autoExecuteRecording.value = false
    elementRecordEnabled.value = false
  }
  return ok
}

function currentHierarchyCacheKey() {
  const device = deviceStore.activeDevice
  return [
    device?.udid ?? '',
    device?.platform ?? '',
    device?.wda_url ?? '',
    elementPackageName.value.trim(),
  ].join('|')
}

function markHierarchyCacheDirty() {
  hierarchyPrewarmed.value = false
  lastHierarchyCacheKey = ''
  lastHierarchyRefreshAt = 0
  if (hierarchyRefreshTimer !== null) {
    window.clearTimeout(hierarchyRefreshTimer)
    hierarchyRefreshTimer = null
  }
}

function scheduleAutoExecuteHierarchyRefresh(_reason: string, delayMs = AUTOEXECUTE_HIERARCHY_REFRESH_DELAY_MS) {
  // Skip during live touch/drag to avoid ADB contention with scrcpy control
  if (liveTouchActive) return
  if (!autoExecuteRecording.value || !elementRecordEnabled.value || autoExecutePrewarming.value) return
  if (!deviceStore.activeDevice) return
  if (hierarchyRefreshTimer !== null) {
    window.clearTimeout(hierarchyRefreshTimer)
  }
  const elapsed = performance.now() - lastHierarchyRefreshAt
  const cooldownDelay = Math.max(0, AUTOEXECUTE_HIERARCHY_REFRESH_MIN_INTERVAL_MS - elapsed)
  hierarchyRefreshTimer = window.setTimeout(async () => {
    hierarchyRefreshTimer = null
    // Re-check liveTouchActive in case a new touch started during timeout
    if (liveTouchActive) return
    if (hierarchyRefreshInFlight || !autoExecuteRecording.value || !elementRecordEnabled.value) return
    hierarchyRefreshInFlight = true
    try {
      await warmAutoExecuteHierarchyCache({ force: true, silent: true })
    } finally {
      hierarchyRefreshInFlight = false
    }
  }, Math.max(delayMs, cooldownDelay))
}

async function appendRecordedClick(point: { x: number; y: number }) {
  flushRecordedInput()
  const x = Math.round(point.x)
  const y = Math.round(point.y)
  if (!autoExecuteRecording.value || !elementRecordEnabled.value || !deviceStore.activeDevice) {
    return
  }

  autoExecuteStatusText.value = '正在用缓存控件树生成 XPath'
  const response = await locateRecordedClick({ x, y })
  if (response?.found && response.element) {
    if (isInputElement(response.element)) {
      const xpath = response.element.xpath || response.element.hierarchy_xpath || ''
      if (!xpath) {
        ElMessage.warning('输入框缺少 XPath，未写入脚本')
        return
      }
      pendingRecordedInputTarget.value = {
        xpath,
        label: xpath,
      }
      autoExecuteStatusText.value = `已选中输入框：${xpath}`
      ElMessage.success('已选中输入框，输入文字后会写入 auto_execute.input')
      return
    }
    appendCommandToActiveScript(response.generated_code)
    const label = response.element.xpath || response.element.hierarchy_xpath
    autoExecuteStatusText.value = `已写入 XPath：${label}`
    ElMessage.success(`已录制 XPath：${label}`)
  } else if (response) {
    const isOutsideTarget = response.message.includes('outside target package')
    autoExecuteStatusText.value = isOutsideTarget
      ? '点击不属于目标应用，已忽略'
      : '未命中 UI 元素，未写入坐标兜底'
    ElMessage.warning(isOutsideTarget ? '点击不属于当前录制应用，已忽略' : '没有命中 UI 元素，严格模式未写入坐标兜底')
  }
}

function isInputElement(element: DeviceUiLocateResponse['element']): boolean {
  if (!element) return false
  if (element.input_capable) return true
  const className = element.class_name.toLowerCase()
  return ['edittext', 'autocompletetextview', 'textfield', 'securetextfield', 'textarea'].some(marker => className.includes(marker))
}

function buildAssertionCommand(type: AutomationAssertType = assertType.value): string | null {
  if (type === 'text_visible') {
    const text = assertTargetText.value.trim()
    if (!text) {
      ElMessage.warning('请输入文本内容')
      return null
    }
    return `auto_execute.assert_text_visible(${pythonStringLiteral(text)})`
  }
  if (type === 'element_exists') {
    const resourceId = assertTargetResourceId.value.trim()
    if (!resourceId) {
      ElMessage.warning('请输入 Resource ID')
      return null
    }
    return `auto_execute.wait_for_element(resource_id=${pythonStringLiteral(resourceId)})\nauto_execute.assert_element_exists(resource_id=${pythonStringLiteral(resourceId)})`
  }
  if (type === 'ocr_contains') {
    const text = assertTargetText.value.trim()
    if (!text) {
      ElMessage.warning('请输入 OCR 文本')
      return null
    }
    return `auto_execute.assert_ocr_contains(${pythonStringLiteral(text)})`
  }
  if (type === 'image_exists') {
    const path = assertImageTemplateName.value.trim()
    if (!path) {
      ElMessage.warning('请先设置模板图片路径或截取基准图')
      return null
    }
    return `auto_execute.assert_image_exists(${pythonStringLiteral(path)}, threshold=${Number(assertImageThreshold.value.toFixed(2))})`
  }
  const appId = assertTargetAppId.value.trim()
  if (!appId) {
    ElMessage.warning('请输入 App 包名/Bundle ID')
    return null
  }
  return `auto_execute.assert_app_foreground(${pythonStringLiteral(appId)})`
}

function addAssertToRecording(type: AutomationAssertType = assertType.value) {
  assertType.value = type
  if (!deviceStore.activeDevice || activeScriptContent.value === null) {
    ElMessage.warning('请先打开脚本并选择在线设备')
    return
  }
  flushRecordedInput()
  const command = buildAssertionCommand(type)
  if (!command) return

  if (!autoExecuteRecording.value) {
    autoExecuteStatusText.value = `断言已就绪：${command}`
    ElMessage.info('当前未开启录制，已保留断言配置；开始录制后再写入脚本')
    return
  }

  appendCommandToActiveScript(command)
  autoExecuteStatusText.value = `已写入断言：${command}`
  ElMessage.success('已写入断言到当前脚本')
}

async function runAssertImageCompare() {
  const device = runnableActiveDevice()
  if (!device) return
  const path = assertImageTemplateName.value.trim()
  if (!path) { ElMessage.warning('请先设置模板图片路径或截取基准图'); return }
  imageCompareBusy.value = true
  imageCompareResult.value = null
  try {
    const result = await imageCompare(device.udid, device.platform, path, assertImageThreshold.value, device.wda_url ?? null)
    imageCompareResult.value = result
    if (result.matched) {
      ElMessage.success(`图像匹配成功：得分 ${result.score.toFixed(2)}`)
    } else {
      ElMessage.warning(`图像未匹配：得分 ${result.score.toFixed(2)}，阈值 ${result.threshold}`)
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '图像对比失败')
  } finally {
    imageCompareBusy.value = false
  }
}

async function captureAssertTemplate() {
  const device = runnableActiveDevice()
  if (!device) return
  imageCompareBusy.value = true
  try {
    const result = await captureTemplate(device.udid, device.platform, null, device.wda_url ?? null)
    assertImageTemplateName.value = result.template_path
    autoExecuteStatusText.value = `已更新模板：${result.template_name}`
    ElMessage.success(`已截取基准图：${result.template_name}`)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '截取基准图失败')
  } finally {
    imageCompareBusy.value = false
  }
}

async function handleAutoExecuteAddAssert(type: string) {
  const nextType = type as AutomationAssertType
  if (['element_exists', 'text_visible', 'ocr_contains', 'image_exists', 'app_foreground'].includes(nextType)) {
    addAssertToRecording(nextType)
  }
}

function queueRecordedInput(value: string) {
  if (!autoExecuteRecording.value || activeScriptContent.value === null || !value) return
  pendingRecordedInput += value
  if (inputFlushTimer !== null) {
    window.clearTimeout(inputFlushTimer)
  }
  inputFlushTimer = window.setTimeout(flushRecordedInput, 350)
}

function flushRecordedInput() {
  if (inputFlushTimer !== null) {
    window.clearTimeout(inputFlushTimer)
    inputFlushTimer = null
  }
  if (!pendingRecordedInput) return
  if (pendingRecordedInputTarget.value) {
    appendCommandToActiveScript(
      `auto_execute.input(xpath=${pythonStringLiteral(pendingRecordedInputTarget.value.xpath)}, text=${pythonStringLiteral(pendingRecordedInput)})`,
    )
  } else {
    appendCommandToActiveScript(`auto_execute.input(${pythonStringLiteral(pendingRecordedInput)})`)
  }
  pendingRecordedInput = ''
  pendingRecordedInputTarget.value = null
}

function handleScreenKeyDown(event: KeyboardEvent) {
  if (!deviceStore.activeDevice || event.ctrlKey || event.metaKey || event.altKey) return

  if (event.key.length === 1) {
    event.preventDefault()
    screen.sendControl({ type: 'text', text: event.key })
    queueRecordedInput(event.key)
    return
  }

  const keyCommand = SCREEN_KEYCODE_MAP[event.key]
  if (!keyCommand) return
  event.preventDefault()
  flushRecordedInput()
  screen.sendKey(keyCommand.keycode)
  if (autoExecuteRecording.value) {
    appendCommandToActiveScript(keyCommand.expr)
    scheduleAutoExecuteHierarchyRefresh(`key:${event.key}`)
  }
}

function handleScreenPaste(event: ClipboardEvent) {
  const text = event.clipboardData?.getData('text') ?? ''
  if (!deviceStore.activeDevice || !text) return
  event.preventDefault()
  screen.sendControl({ type: 'text', text })
  queueRecordedInput(text)
  flushRecordedInput()
}

// AutoExecute functions
async function startAutoExecuteRecording() {
  if (!deviceStore.activeDevice) {
    ElMessage.warning('请先选择一个设备')
    return
  }
  if (autoExecuteRecording.value) {
    flushRecordedInput()
    autoExecuteRecording.value = false
    elementRecordEnabled.value = false
    autoExecutePrewarming.value = false
    autoExecutePackageName.value = ''
    pendingRecordedInputTarget.value = null
    pendingRecordedInput = ''
    markHierarchyCacheDirty()
    ElMessage.info('已停止控件录制')
    return
  }

  if (deviceStore.activeDevice.platform === 'ios') {
    const defaultBundle = autoExecutePackageName.value || ''
    try {
      const { value } = await ElMessageBox.prompt(
        '请输入当前要录制的 iOS App Bundle ID。该值会写入 auto_execute.launch(...)，用于后续回归回放。',
        '确认 iOS 目标应用',
        {
          inputValue: defaultBundle,
          inputPlaceholder: '例如 com.example.app',
          confirmButtonText: '开始录制',
          cancelButtonText: '取消',
        },
      )
      const bundleId = String(value || '').trim()
      if (!bundleId) {
        ElMessage.warning('Bundle ID 不能为空')
        return
      }
      autoExecutePackageName.value = bundleId
      if (!(await ensureAutoExecuteScript(bundleId))) return
      appendLaunchLine(bundleId)
      await doStartRecording(bundleId)
      if (autoExecuteRecording.value && !latestScreenshot.value) {
        await takeScreenshot()
      }
    } catch {
      // user cancelled
    }
    return
  }

  // Auto-detect Android current app package name
  try {
    const result = await getCurrentApp(deviceStore.activeDevice.udid)
    if (!result.package_name) {
      ElMessage.warning('无法识别当前应用包名，请确保设备上有应用在前台运行')
      return
    }
    const packageName = result.package_name
    autoExecutePackageName.value = packageName

    if (!(await ensureAutoExecuteScript(packageName))) return
    appendLaunchLine(packageName)

    await doStartRecording(packageName)
  } catch (error) {
    ElMessage.error(error instanceof Error ? `获取包名失败: ${error.message}` : '获取包名失败')
  }
}

async function ensureAutoExecuteScript(appId: string, platform?: string): Promise<boolean> {
  if (activeScriptContent.value !== null) return true

  const safeAppId = appId.replace(/[^A-Za-z0-9_.-]/g, '_') || 'device'
  const stamp = new Date().toISOString().replace(/[-:.TZ]/g, '').slice(0, 14)
  const scriptName = `autoexecute_${safeAppId}_${stamp}.py`
  const script = await scriptStore.createScript(scriptName, '# AutoExecute recording\n', platform ?? deviceStore.activeDevice?.platform ?? 'android')
  if (!script) {
    ElMessage.error(scriptStore.error ?? '创建录制脚本失败')
    return false
  }
  await openScript(script)
  ElMessage.info(`已自动创建录制脚本：${script.name}`)
  return activeScriptContent.value !== null
}

function appendLaunchLine(appId: string) {
  if (activeScriptContent.value === null) return
  const launchLine = `auto_execute.launch(${pythonStringLiteral(appId)})`
  const legacyLaunchLine = `launch(${pythonStringLiteral(appId)})`
  const content = activeScriptContent.value.trim()
  if (!content.includes(launchLine) && !content.includes(legacyLaunchLine)) {
    activeScriptContent.value = `${launchLine}\n${content ? content + '\n' : ''}`
    onScriptEdit()
    ElMessage.success(`已添加 ${launchLine}`)
  }
}

async function doStartRecording(packageName: string) {
  if (!deviceStore.activeDevice) return

  if (elementPackageName.value !== packageName) {
    markHierarchyCacheDirty()
  }
  autoExecuteRecording.value = true
  elementRecordEnabled.value = false
  elementPackageName.value = packageName
  pendingRecordedInputTarget.value = null
  pendingRecordedInput = ''
  ElMessage.success(`开始录制 ${packageName} 的控件操作`)
  if (deviceStore.activeDevice.platform === 'ios') {
    const ok = await prewarmBeforeRecording()
    if (ok) {
      autoExecuteStatusText.value = '点击截图录制控件操作'
    }
    return
  }
  await prewarmBeforeRecording()
}

function stopAutoExecuteRecording() {
  flushRecordedInput()
  autoExecuteRecording.value = false
  elementRecordEnabled.value = false
  autoExecutePrewarming.value = false
  pendingRecordedInputTarget.value = null
  autoExecuteStatusText.value = ''
  markHierarchyCacheDirty()
  ElMessage.info('已停止控件录制')
}

async function playbackRecording() {
  const device = runnableActiveDevice()
  if (!device) return
  if (!activeScriptPath.value) {
    ElMessage.warning('请先打开一个脚本文件')
    return
  }
  if (activeScriptDirty.value) {
    ElMessage.warning('请先保存当前脚本')
    return
  }

  autoExecutePlaying.value = true
  terminal.clear()
  terminal.addLine('system', `Starting ${activeScriptPath.value} on ${device.udid}`)
  try {
    ElMessage.info('开始回放脚本...')
    const result = await scriptStore.runActiveScriptStream(device.udid, {
      platform: device.platform,
      wdaUrl: device.wda_url ?? null,
    })
    if (result) {
      terminal.connect(result.run_id)
      const unwatch = watch(() => terminal.isRunning.value, (running) => {
        if (!running) {
          autoExecutePlaying.value = false
          if (terminal.lastReturnCode.value === 0) {
            ElMessage.success('脚本回放完成')
          } else {
            ElMessage.error(`脚本回放失败: code ${terminal.lastReturnCode.value}`)
          }
          unwatch()
        }
      })
    } else {
      autoExecutePlaying.value = false
      terminal.addLine('stderr', scriptStore.error || 'Process did not start')
      terminal.addLine('exit', 'Process did not start')
    }
  } catch (error) {
    autoExecutePlaying.value = false
    const message = error instanceof Error ? error.message : '脚本回放失败'
    terminal.addLine('stderr', message)
    ElMessage.error(message)
  }
}

// Visual click
async function clickByText(textOverride?: string) {
  const text = (textOverride ?? ocrClickText.value).trim()
  if (!deviceStore.activeDevice || !text) return
  if (activeScriptContent.value === null) {
    ElMessage.warning('请先打开一个脚本文件')
    return
  }
  visualBusy.value = true
  try {
    const response = await clickDeviceText(deviceStore.activeDevice.udid, text, true)
    if (!response.found || response.x == null || response.y == null) {
      ElMessage.warning(`没有识别到文字：${text}`)
      return
    }
    appendCommandToActiveScript(`ocr.click(${pythonStringLiteral(text)})`)
    ElMessage.success(`已点击文字：${response.text || text}`)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : 'OCR 点击失败')
  } finally {
    visualBusy.value = false
  }
}

function handleTemplateFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  templateClickFile.value = input.files?.[0] ?? null
}

async function clickByTemplate(payload?: { file: File; threshold: number }) {
  const templateFile = payload?.file ?? templateClickFile.value
  if (!deviceStore.activeDevice || !templateFile) return
  if (activeScriptContent.value === null) {
    ElMessage.warning('请先打开一个脚本文件')
    return
  }
  visualBusy.value = true
  try {
    const threshold = payload?.threshold ?? Number(templateThreshold.value.toFixed(2))
    const response = await clickDeviceTemplate(deviceStore.activeDevice.udid, templateFile, threshold, true)
    if (!response.found || response.x == null || response.y == null) {
      ElMessage.warning(`没有匹配到图像：${templateFile.name}`)
      return
    }
    const scriptTemplatePath = response.template_path || `templates/${templateFile.name}`
    appendCommandToActiveScript(`image.click(${pythonStringLiteral(scriptTemplatePath)}, threshold=${threshold})`)
    ElMessage.success(`已点击图像坐标：${response.x}, ${response.y}`)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '模板点击失败')
  } finally {
    visualBusy.value = false
  }
}

// Screenshot
async function takeScreenshot() {
  if (!deviceStore.activeDevice) return
  screenshotLoading.value = deviceStore.activeDevice.udid
  try {
    latestScreenshot.value = await captureDeviceScreenshot(deviceStore.activeDevice.udid, {
      platform: deviceStore.activeDevice.platform,
      wdaUrl: deviceStore.activeDevice.wda_url ?? null,
    })
    ElMessage.success('截图已保存')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '截图失败')
  } finally {
    screenshotLoading.value = null
  }
}

function imageEventToDevicePoint(event: PointerEvent): { x: number; y: number } | null {
  const image = screenshotImageRef.value
  if (!image || !image.naturalWidth || !image.naturalHeight) return null
  const rect = image.getBoundingClientRect()
  if (rect.width <= 0 || rect.height <= 0) return null
  const x = Math.round((event.clientX - rect.left) * (image.naturalWidth / rect.width))
  const y = Math.round((event.clientY - rect.top) * (image.naturalHeight / rect.height))
  if (x < 0 || y < 0 || x > image.naturalWidth || y > image.naturalHeight) return null
  return { x, y }
}

function handleScreenshotPointerDown(event: PointerEvent) {
  const point = imageEventToDevicePoint(event)
  if (!point) return
  const target = event.currentTarget as HTMLElement
  target.setPointerCapture(event.pointerId)
  screenshotPointerStart.value = { ...point, at: performance.now() }
}

async function handleScreenshotPointerUp(event: PointerEvent) {
  const start = screenshotPointerStart.value
  const end = imageEventToDevicePoint(event)
  screenshotPointerStart.value = null
  if (!start || !end || !deviceStore.activeDevice) return

  const distance = Math.hypot(end.x - start.x, end.y - start.y)
  const duration = Math.max(80, Math.round(performance.now() - start.at))
  if (visualRecordMode.value !== 'none') {
    const handled = handleVisualRecordGesture(start, end, distance, duration)
    if (handled) {
      try {
        if (visualRecordMode.value === 'swipe' && distance >= TAP_DISTANCE_PX) {
          await swipeDevice(
            deviceStore.activeDevice.udid,
            Math.round(start.x),
            Math.round(start.y),
            Math.round(end.x),
            Math.round(end.y),
            duration,
            deviceStore.activeDevice.platform,
          )
        } else if (distance < TAP_DISTANCE_PX) {
          await tapDevicePoint(deviceStore.activeDevice.udid, {
            x: Math.round(end.x),
            y: Math.round(end.y),
            platform: deviceStore.activeDevice.platform,
            wda_url: deviceStore.activeDevice.wda_url ?? null,
          })
        }
      } catch (error) {
        ElMessage.error(error instanceof Error ? error.message : '设备操作失败')
      }
      window.setTimeout(() => {
        void takeScreenshot()
      }, 600)
      return
    }
  }
  if (distance >= TAP_DISTANCE_PX || duration >= 500) return

  void appendRecordedClick(end)
  try {
    await tapDevicePoint(deviceStore.activeDevice.udid, {
      x: Math.round(end.x),
      y: Math.round(end.y),
      platform: deviceStore.activeDevice.platform,
      wda_url: deviceStore.activeDevice.wda_url ?? null,
    })
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : 'iOS 点击失败')
    return
  }
  window.setTimeout(() => {
    void takeScreenshot()
  }, 600)
  scheduleAutoExecuteHierarchyRefresh('screenshot_tap')
}

function handleScreenshotPointerCancel() {
  screenshotPointerStart.value = null
}

// Text input for Electron scrcpy control panel
const deviceTextInput = ref('')

async function sendDeviceText() {
  const text = deviceTextInput.value.trim()
  if (!text || !deviceStore.activeDevice) return
  try {
    screen.sendControl({ type: 'text', text })
    deviceTextInput.value = ''
  } catch { /* ignore */ }
}

// Key events
const KEYCODE_MAP: Record<string, { expr: string; keycode: number }> = {
  BACK: { expr: 'adb.back()', keycode: 4 },
  HOME: { expr: 'adb.home()', keycode: 3 },
  APP_SWITCH: { expr: 'adb.key(187)', keycode: 187 },
}

const SCREEN_KEYCODE_MAP: Record<string, { expr: string; keycode: number }> = {
  Backspace: { expr: 'adb.key(67)', keycode: 67 },
  Enter: { expr: 'adb.key(66)', keycode: 66 },
  Tab: { expr: 'adb.key(61)', keycode: 61 },
  Escape: { expr: 'adb.key(111)', keycode: 111 },
}

async function sendKeyEvent(key: string) {
  if (!deviceStore.activeDevice) return
  const command = KEYCODE_MAP[key]
  if (!command) return
  flushRecordedInput()
  if (autoExecuteRecording.value) {
    appendCommandToActiveScript(command.expr)
    scheduleAutoExecuteHierarchyRefresh(`nav:${key}`)
  }
  screen.sendKey(command.keycode)
}

// Script tab management
async function openScript(sf: { path: string; name: string }) {
  if (openScriptTabs.value.some(t => t.path === sf.path)) {
    selectScriptTab(sf.path)
    return
  }
  try {
    const content = await scriptStore.openScript(sf as any)
    openScriptTabs.value.push({
      path: sf.path,
      name: sf.name,
      dirty: false,
      content: scriptStore.scriptContent,
    })
    selectScriptTab(sf.path)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '加载脚本失败')
  }
}

function selectScriptTab(path: string | null) {
  activeScriptPath.value = path
  const tab = openScriptTabs.value.find(t => t.path === path)
  activeScriptContent.value = tab?.content ?? null
  scriptStore.runResult = null
}

function onScriptEdit() {
  const tab = openScriptTabs.value.find(t => t.path === activeScriptPath.value)
  if (tab) {
    tab.content = activeScriptContent.value ?? ''
    if (!tab.dirty) tab.dirty = true
  }
  scriptStore.runResult = null
}

async function saveActiveScript() {
  if (!activeScriptPath.value || activeScriptContent.value === null) return false
  // Sync content to store
  scriptStore.scriptContent = activeScriptContent.value
  if (scriptStore.activeScript?.path !== activeScriptPath.value) {
    const sf = scriptStore.scripts.find(s => s.path === activeScriptPath.value)
    if (sf) scriptStore.activeScript = sf
  }
  const ok = await scriptStore.saveActiveScript()
  if (ok) {
    const tab = openScriptTabs.value.find(t => t.path === activeScriptPath.value)
    if (tab) {
      tab.content = activeScriptContent.value
      tab.dirty = false
    }
    ElMessage.success('已保存')
    return true
  } else {
    ElMessage.error(scriptStore.error ?? '保存失败')
    return false
  }
}

async function runActiveScript() {
  if (!activeScriptPath.value) return
  const device = runnableActiveDevice()
  if (!device) return
  scriptStore.scriptContent = activeScriptContent.value ?? ''
  if (scriptStore.activeScript?.path !== activeScriptPath.value) {
    const sf = scriptStore.scripts.find(s => s.path === activeScriptPath.value)
    if (sf) scriptStore.activeScript = sf
  }
  if (!scriptStore.activeScript) {
    terminal.clear()
    terminal.addLine('stderr', 'No active script selected')
    terminal.addLine('exit', 'Process did not start')
    return
  }
  if (activeScriptDirty.value) {
    const saved = await saveActiveScript()
    if (!saved) return
  }
  terminal.clear()
  terminal.addLine('system', `Starting ${activeScriptPath.value} on ${device.udid}`)
  const result = await scriptStore.runActiveScriptStream(device.udid, {
    platform: device.platform,
    wdaUrl: device.wda_url ?? null,
  })
  if (result) {
    terminal.connect(result.run_id)
  } else {
    const message = scriptStore.error || 'Process did not start'
    terminal.addLine('stderr', message)
    terminal.addLine('exit', 'Process did not start')
    if (scriptStore.error) ElMessage.error(scriptStore.error)
  }
}

async function cancelScriptExecution() {
  await scriptStore.cancelActiveRun()
  terminal.addLine('system', 'Script execution cancelled')
}

function closeScriptTab(path: string) {
  const idx = openScriptTabs.value.findIndex(t => t.path === path)
  if (idx < 0) return
  openScriptTabs.value.splice(idx, 1)
  if (activeScriptPath.value === path) {
    selectScriptTab(openScriptTabs.value[idx - 1]?.path ?? openScriptTabs.value[idx]?.path ?? null)
  }
}

async function confirmDeleteScript(sf: { path: string; name: string }) {
  try {
    await ElMessageBox.confirm(`删除脚本 "${sf.name}"？`, '确认', { type: 'warning' })
  } catch { return }
  const ok = await scriptStore.deleteScript(sf.path)
  if (ok) {
    closeScriptTab(sf.path)
    ElMessage.success('已删除')
  } else {
    ElMessage.error(scriptStore.error ?? '删除失败')
  }
}

// Auto-refresh devices — slows to 15s when streaming to avoid ADB contention
const { start: startPolling, stop: stopPolling, updateInterval: setPollingInterval } = usePolling(
  async () => {
    await deviceStore.loadDevices(false)
    autoConnectActiveDevice()
  },
  { interval: 3000 },
)

// Slow device polling when screen is streaming (avoids ADB/USB contention with scrcpy)
watch(
  () => screen.state.value.isConnected,
  (connected) => {
    setPollingInterval(connected ? 15_000 : 3_000)
  },
)

onMounted(async () => {
  loadDevices()
  await scriptStore.loadScriptTree()
  scriptStore.loadPythonEnvs()
  startPolling()
  // Auto-open demo.py if no script tab is open yet
  if (openScriptTabs.value.length === 0) {
    const demoFile = findFileInTree('demo.py', scriptStore.scriptTree)
    if (demoFile) {
      await openScript(demoFile)
      // Auto-expand the parent folder containing demo.py
      const parentPath = demoFile.path.includes('/') ? demoFile.path.split('/').slice(0, -1).join('/') : ''
      if (parentPath) {
        expandedFolders.value.add(parentPath)
      }
    }
  }
})

watch(
  () => [
    deviceStore.activeDevice?.udid,
    deviceStore.activeDevice?.status,
    deviceStore.activeDevice?.platform,
  ],
  () => {
    markHierarchyCacheDirty()
    autoConnectActiveDevice()
  },
  { flush: 'post' },
)

onBeforeUnmount(() => {
  stopPolling()
  flushRecordedInput()
  markHierarchyCacheDirty()
  // Disconnect on route change — the next page will re-connect with
  // its own options (e.g. control:true vs control:false).
  screen.disconnect()
})
</script>

<template>
  <div class="page-shell">
    <!-- Top Bar -->
    <header class="topbar">
      <div class="device-info">
        <span class="label">当前设备信息</span>
        <span v-if="deviceStore.activeDevice" class="value">
          {{ deviceStore.activeDevice.model || deviceStore.activeDevice.product || deviceStore.activeDevice.udid }}
          <el-tag :type="statusType(deviceStore.activeDevice.status)" effect="light" size="small">{{ deviceStore.activeDevice.status }}</el-tag>
          <el-tag size="small" type="info">{{ deviceStore.activeDevice.platform }}</el-tag>
        </span>
        <span v-else class="value empty">未选择设备</span>
      </div>
      <div class="topbar-actions">
        <el-dropdown v-if="deviceStore.devices.length > 0" trigger="click" @command="connectScreen">
          <el-button type="primary" size="small">
                切换设备<el-icon class="el-icon--right"><ArrowDown /></el-icon>
          </el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item
                v-for="device in deviceStore.devices"
                :key="device.udid"
                :command="device"
                :disabled="device.status !== 'online'"
              >
                {{ device.model || device.udid }} ({{ device.status }})
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
        <el-button :icon="Refresh" :loading="deviceStore.loading" size="small" @click="loadDevices">刷新</el-button>
      </div>
    </header>

    <!-- Workspace -->
    <div class="workspace">
      <!-- Activity Bar -->
      <div class="activity-bar">
        <button
          class="activity-item"
          :class="{ active: activeLeftTab === 'scripts' && leftPanelOpen }"
          title="测试脚本"
          @click="toggleLeftPanel('scripts')"
        >
          <el-icon :size="20"><Document /></el-icon>
        </button>
        <button
          class="activity-item"
          :class="{ active: activeLeftTab === 'devices' && leftPanelOpen }"
          title="自动化"
          @click="toggleLeftPanel('devices')"
        >
          <el-icon :size="20"><Cellphone /></el-icon>
        </button>
        <button
          class="activity-item"
          :class="{ active: activeLeftTab === 'automation' && leftPanelOpen }"
          title="断言 & 图像对比"
          @click="toggleLeftPanel('automation')"
        >
          <el-icon :size="20"><CircleCheck /></el-icon>
        </button>
        <div class="activity-spacer" />
        <button
          class="activity-item"
          :class="{ active: activeLeftTab === 'screen' && leftPanelOpen }"
          title="投屏控制"
          @click="toggleLeftPanel('screen')"
        >
          <el-icon :size="20"><Monitor /></el-icon>
        </button>
      </div>

      <!-- Left Sidebar (collapsible) -->
      <div class="left-sidebar" :class="{ collapsed: !leftPanelOpen }">
        <div class="sidebar-header">
          <span class="sidebar-title">{{ sidebarTitle }}</span>
          <button class="sidebar-close" @click="leftPanelOpen = false">
            <el-icon><Fold /></el-icon>
          </button>
        </div>

        <div class="sidebar-body">
          <!-- Scripts tab -->
          <template v-if="activeLeftTab === 'scripts'">
            <div class="script-toolbar">
              <span class="toolbar-title">SCRIPTS</span>
              <div class="toolbar-actions">
                <button class="toolbar-btn" title="新建脚本" @click="startRootCreate('file')">
                  <el-icon :size="14"><Document /></el-icon>
                </button>
                <button class="toolbar-btn" title="新建文件夹" @click="startRootCreate('folder')">
                  <el-icon :size="14"><FolderOpened /></el-icon>
                </button>
                <button class="toolbar-btn" title="刷新" @click="scriptStore.loadScriptTree()">
                  <el-icon :size="14"><Refresh /></el-icon>
                </button>
              </div>
            </div>
            <!-- Inline creation at root level -->
            <div v-if="rootCreating" class="root-create-row">
              <span class="expand-arrow placeholder" />
              <el-icon class="node-icon">
                <FolderOpened v-if="rootCreateType === 'folder'" />
                <Document v-else />
              </el-icon>
              <input
                ref="rootCreateInput"
                v-model="rootCreateName"
                class="inline-input"
                :placeholder="rootCreateType === 'folder' ? '文件夹名称' : '脚本名称 (.py)'"
                @keydown.enter="confirmRootCreate"
                @keydown.escape="rootCreating = false"
              />
            </div>
            <div class="file-tree" v-loading="scriptStore.loading">
              <div v-if="scriptStore.scriptTree.length === 0 && !scriptStore.loading" class="file-tree-empty">
                暂无脚本 — 点击上方按钮新建
              </div>
              <FileTreeNode
                v-for="item in scriptStore.scriptTree"
                :key="item.path"
                :item="item"
                :active-path="activeScriptPath"
                :expanded-folders="expandedFolders"
                @toggle-folder="toggleFolder"
                @open-file="openScriptFile"
                @delete-file="confirmDeleteScript"
                @delete-folder="confirmDeleteFolder"
                @refresh="scriptStore.loadScriptTree()"
              />
            </div>
          </template>

          <!-- Devices tab -->
          <template v-if="activeLeftTab === 'devices'">
            <div class="device-list-mini" v-loading="deviceStore.loading">
              <div
                v-for="device in deviceStore.devices"
                :key="device.udid"
                class="device-mini-item"
                :class="{ active: deviceStore.activeDevice?.udid === device.udid }"
                @click="connectScreen(device)"
              >
                <el-icon><Cellphone /></el-icon>
                <div class="device-mini-info">
                  <span class="device-mini-name">{{ device.model || device.product || device.udid }}</span>
                  <span class="device-mini-id">{{ device.udid }}</span>
                </div>
                <el-tag :type="statusType(device.status)" effect="light" size="small">{{ device.status }}</el-tag>
              </div>
            </div>
          </template>

          <!-- Screen tab - simplified, no AutoExecute here -->
          <template v-if="activeLeftTab === 'screen'">
            <div class="screen-controls">
              <el-button v-if="deviceStore.activeDevice" :icon="Camera" :loading="screenshotLoading === deviceStore.activeDevice.udid" size="small" @click="takeScreenshot">截图</el-button>
              <div class="screen-info" v-if="deviceStore.activeDevice">
                <div>分辨率: {{ screen.state.value.width || '-' }} × {{ screen.state.value.height || '-' }}</div>
                <div>Provider: {{ screen.state.value.provider || '-' }}</div>
                <div>状态: {{ screen.state.value.isConnected ? '已连接' : '未连接' }}</div>
                <div>帧率: {{ screenFrameLabel || '-' }}</div>
              </div>
              <div class="visual-actions" v-if="deviceStore.activeDevice">
                <div class="sidebar-section-title compact">基础录制</div>
                <div class="basic-record-row">
                  <el-button
                    size="small"
                    :type="visualRecordMode === 'click' ? 'primary' : 'default'"
                    :disabled="!activeScriptPath"
                    @click="toggleVisualRecordMode('click')"
                  >
                    坐标点击
                  </el-button>
                  <el-button
                    size="small"
                    :type="visualRecordMode === 'swipe' ? 'primary' : 'default'"
                    :disabled="!activeScriptPath"
                    @click="toggleVisualRecordMode('swipe')"
                  >
                    滑动
                  </el-button>
                  <el-button
                    size="small"
                    :type="visualRecordMode === 'input' ? 'primary' : 'default'"
                    :disabled="!activeScriptPath"
                    @click="toggleVisualRecordMode('input')"
                  >
                    输入
                  </el-button>
                </div>
                <el-input
                  v-model="visualRecordInputText"
                  size="small"
                  placeholder="输入模式内容，如 12234567"
                  :disabled="!activeScriptPath"
                />
                <div v-if="visualRecordMode !== 'none'" class="visual-record-hint">
                  {{ visualRecordMode === 'click' ? '点击投屏画面，写入 auto_execute.click(x, y)' : visualRecordMode === 'swipe' ? '在投屏画面拖动，写入 auto_execute.swipe(...)' : '填写内容后点击目标输入框，写入 click + input' }}
                </div>

                <div class="sidebar-section-title compact">视觉点击</div>
                <div class="visual-action-row">
                  <el-input
                    v-model="ocrClickText"
                    :disabled="visualBusy"
                    size="small"
                    placeholder="输入文字后点击"
                    @keyup.enter="clickByText"
                  />
                  <el-button
                    :icon="Search"
                    :loading="visualBusy"
                    :disabled="!ocrClickText.trim()"
                    size="small"
                    type="primary"
                    @click="clickByText"
                  />
                </div>
                <label class="template-picker">
                  <el-icon><Picture /></el-icon>
                  <span>{{ templateClickFile?.name || '选择图标模板' }}</span>
                  <input accept="image/*" type="file" @change="handleTemplateFileChange" />
                </label>
                <div class="threshold-row">
                  <span>阈值</span>
                  <el-slider v-model="templateThreshold" :min="0.7" :max="1" :step="0.01" size="small" />
                </div>
                <el-button
                  :icon="Picture"
                  :loading="visualBusy"
                  :disabled="!templateClickFile"
                  size="small"
                  @click="clickByTemplate"
                >
                  匹配并点击
                </el-button>
              </div>
            </div>
          </template>

          <!-- Automation tab — assertions & image compare -->
          <template v-if="activeLeftTab === 'automation'">
            <AutomationSidebar
              :device-ready="Boolean(deviceStore.activeDevice)"
              :script-ready="activeScriptContent !== null"
              :recording="autoExecuteRecording"
              :active-script-path="activeScriptPath"
              :status-text="autoExecuteStatusText"
              :assert-type="assertType"
              :assert-target-text="assertTargetText"
              :assert-target-resource-id="assertTargetResourceId"
              :assert-target-app-id="assertTargetAppId"
              :assert-image-threshold="assertImageThreshold"
              :assert-image-template-name="assertImageTemplateName"
              :image-compare-busy="imageCompareBusy"
              :image-compare-result="imageCompareResult"
              @update-assert-type="assertType = $event"
              @update-assert-target-text="assertTargetText = $event"
              @update-assert-target-resource-id="assertTargetResourceId = $event"
              @update-assert-target-app-id="assertTargetAppId = $event"
              @update-assert-image-threshold="assertImageThreshold = $event"
              @update-assert-image-template-name="assertImageTemplateName = $event"
              @add-assert="addAssertToRecording"
              @capture-template="captureAssertTemplate"
              @run-image-compare="runAssertImageCompare"
            />
          </template>
        </div>

        <!-- AutoExecute Panel at bottom of sidebar -->
        <div class="sidebar-footer">
          <AutoExecutePanel
            :recording="autoExecuteRecording"
            :playing="autoExecutePlaying"
            :package-name="autoExecutePackageName"
            :active-script-path="activeScriptPath"
            :platform="deviceStore.activeDevice?.platform"
            :status-text="autoExecuteStatusText"
            :locate-busy="elementLocateBusy || autoExecutePrewarming"
            @start-recording="startAutoExecuteRecording"
            @playback="playbackRecording"
            @add-assert="handleAutoExecuteAddAssert"
          />
        </div>
      </div>

      <!-- Editor Area -->
      <div class="editor-area">
        <!-- Tab Bar -->
        <div class="tab-bar" v-if="openScriptTabs.length > 0">
          <div
            v-for="tab in openScriptTabs"
            :key="tab.path"
            class="tab-item"
            :class="{ active: activeScriptPath === tab.path }"
            @click="selectScriptTab(tab.path)"
          >
            <el-icon><Document /></el-icon>
            <span>{{ tab.name }}{{ tab.dirty ? ' ●' : '' }}</span>
            <button class="tab-close" @click.stop="closeScriptTab(tab.path)">&times;</button>
          </div>
        </div>

        <!-- Editor Content -->
        <div class="editor-content">
          <template v-if="activeScriptContent !== null">
            <div class="script-editor-wrapper">
              <div class="script-editor-toolbar">
                <div class="toolbar-left">
                  <el-button
                    size="small"
                    type="primary"
                    :disabled="!activeScriptDirty"
                    :loading="scriptStore.saving"
                    @click="saveActiveScript"
                  >
                    保存
                  </el-button>
                  <el-select
                    v-if="scriptStore.pythonEnvs"
                    class="python-env-select"
                    size="small"
                    :model-value="scriptStore.selectedPythonPath"
                    @change="handlePythonEnvChange"
                  >
                    <el-option
                      v-for="env in scriptStore.pythonEnvs.envs"
                      :key="env.path"
                      :label="env.name"
                      :value="env.path"
                    />
                  </el-select>
                  <el-button
                    v-if="terminalRunning"
                    size="small"
                    type="danger"
                    @click="cancelScriptExecution"
                  >
                    停止
                  </el-button>
                  <el-button
                    v-else
                    size="small"
                    type="primary"
                    :disabled="!activeRunnableDevice"
                    :loading="scriptStore.running"
                    @click="runActiveScript"
                  >
                    ▶ Run
                  </el-button>
                </div>
                <div class="toolbar-right">
                  <el-tooltip content="缩小字体" placement="bottom">
                    <el-button size="small" :icon="ZoomOut" @click="editorFontSize = Math.max(10, editorFontSize - 1)" />
                  </el-tooltip>
                  <span class="font-size-label">{{ editorFontSize }}px</span>
                  <el-tooltip content="放大字体" placement="bottom">
                    <el-button size="small" :icon="ZoomIn" @click="editorFontSize = Math.min(24, editorFontSize + 1)" />
                  </el-tooltip>
                  <el-divider direction="vertical" />
                  <el-tooltip :content="editorLineNumbers ? '隐藏行号' : '显示行号'" placement="bottom">
                    <el-button size="small" :type="editorLineNumbers ? 'primary' : 'default'" @click="editorLineNumbers = !editorLineNumbers">
                      #
                    </el-button>
                  </el-tooltip>
                  <el-tooltip :content="editorWordWrap ? '取消换行' : '自动换行'" placement="bottom">
                    <el-button size="small" :type="editorWordWrap ? 'primary' : 'default'" @click="editorWordWrap = !editorWordWrap">
                      ↵
                    </el-button>
                  </el-tooltip>
                </div>
              </div>
              <div class="editor-container" :style="{ fontSize: editorFontSize + 'px' }">
                <div v-if="editorLineNumbers" class="line-numbers" aria-hidden="true">
                  <div v-for="(_, i) in (activeScriptContent || '').split('\n')" :key="i" class="line-number">{{ i + 1 }}</div>
                </div>
                <textarea
                  class="script-editor"
                  :class="{ 'with-line-numbers': editorLineNumbers, 'word-wrap': editorWordWrap }"
                  v-model="activeScriptContent"
                  @input="onScriptEdit"
                  spellcheck="false"
                  :style="{ fontSize: editorFontSize + 'px' }"
                />
              </div>
              <TerminalPanel
                :lines="terminalLines"
                :is-running="terminalRunning"
                :is-connected="terminalConnected"
                :last-return-code="terminalReturnCode"
                :duration-ms="terminalDurationMs"
                @clear="terminal.clear"
                @cancel="cancelScriptExecution"
              />
            </div>
          </template>

          <!-- Idle State -->
          <template v-else>
            <div class="idle-page">
              <div class="idle-logo">
                <el-icon :size="64"><Document /></el-icon>
                <h1>脚本编辑器</h1>
              </div>
              <div class="idle-sections">
                <div class="idle-section">
                  <h3>最近脚本</h3>
                  <ul>
                    <li
                      v-for="tab in openScriptTabs.slice(-5)"
                      :key="tab.path"
                      @click="selectScriptTab(tab.path)"
                    >
                      <el-icon><Document /></el-icon>
                      <span>{{ tab.name }}</span>
                    </li>
                    <li v-if="openScriptTabs.length === 0" class="empty">
                      <span>没有最近的脚本</span>
                    </li>
                  </ul>
                </div>
                <div class="idle-section">
                  <h3>新建</h3>
                  <ul>
                    <li @click="startRootCreate('file')">
                      <el-icon><Document /></el-icon>
                      <span>新建脚本...</span>
                    </li>
                  </ul>
                </div>
              </div>
            </div>
          </template>
        </div>
      </div>

      <!-- Right Panel: Screen -->
      <div class="right-panel">
        <div class="panel-heading">
          <div class="screen-meta" v-if="deviceStore.activeDevice">
            <el-tag size="small" :type="screenModeTagType">{{ screenModeLabel }}</el-tag>
            <span class="frame-count">{{ screenFrameLabel }}</span>
            <el-tag v-if="deviceStore.activeDevice.platform === 'android' && screen.state.value.controlConnected" size="small" type="success">scrcpy 实时控制</el-tag>
            <el-tag v-else-if="deviceStore.activeDevice.platform === 'android' && screen.state.value.controlMode === 'fallback'" size="small" type="warning">ADB fallback 控制</el-tag>
            <span class="frame-count" v-if="deviceStore.activeDevice?.platform === 'android' && screen.state.value.isConnected">recv {{ screen.state.value.fps }} fps</span>
          </div>
        </div>

        <div class="screen-container">
          <!-- Electron native embedded scrcpy surface -->
          <div v-if="screen.state.value.mode === 'scrcpy-native' && deviceStore.activeDevice" class="screen-wrapper native-screen-wrapper">
            <div
              :ref="screen.setNativeHost"
              class="native-screen-host"
              tabindex="0"
              @pointerdown="handlePointerDown"
              @pointermove="handlePointerMove"
              @pointerup="handlePointerUp"
              @pointercancel="handlePointerCancel"
              @keydown="handleScreenKeyDown"
              @paste="handleScreenPaste"
            >
              <div v-if="screen.state.value.isLoading" class="native-screen-overlay">
                <el-icon class="is-loading" :size="32"><Loading /></el-icon>
                <span>启动原生投屏...</span>
              </div>
              <div v-else-if="screen.state.value.error" class="native-screen-overlay error">
                <span>{{ screen.state.value.error }}</span>
              </div>
            </div>
          </div>

          <!-- Loading -->
          <div v-else-if="screen.state.value.isLoading" class="screen-loading">
            <el-icon class="is-loading" :size="32"><Loading /></el-icon>
            <span>连接中...</span>
          </div>

          <!-- Error -->
          <div v-else-if="screen.state.value.error" class="screen-error">
            <el-alert :title="screen.state.value.error" type="error" show-icon />
          </div>

          <!-- No device selected -->
          <div v-else-if="!deviceStore.activeDevice" class="screen-empty">
            <el-icon :size="36"><Cellphone /></el-icon>
            <span>选择设备进行投屏</span>
          </div>

          <!-- iOS live stream mode (SocketIO or WebSocket) -->
          <div v-else-if="deviceStore.activeDevice.platform === 'ios'" class="screen-wrapper ios-stream-wrapper">
            <div v-if="screen.state.value.isConnected" class="screen-canvas-container">
              <canvas
                :ref="screen.setCanvas"
                class="screen-canvas"
                :style="{ background: '#000', aspectRatio: screenAspectRatio }"
                tabindex="0"
                @pointerdown="handlePointerDown"
                @pointermove="handlePointerMove"
                @pointerup="handlePointerUp"
                @pointercancel="handlePointerCancel"
                @keydown="handleScreenKeyDown"
              />
            </div>
            <div v-else-if="screen.state.value.isLoading" class="screen-empty">
              <el-icon :size="36" class="is-loading"><Loading /></el-icon>
              <span>正在连接 iOS 投屏...</span>
            </div>
            <div v-else-if="screen.state.value.error" class="screen-empty screen-error">
              <el-icon :size="36"><WarningFilled /></el-icon>
              <span>{{ screen.state.value.error }}</span>
              <el-button type="primary" size="default" @click="connectScreen(deviceStore.activeDevice)">重连</el-button>
            </div>
            <div v-else class="screen-empty">
              <el-icon :size="36"><Cellphone /></el-icon>
              <span>点击"启动投屏"连接 iOS 设备</span>
              <el-button type="primary" size="default" @click="connectScreen(deviceStore.activeDevice)">启动投屏</el-button>
            </div>
          </div>

          <!-- Electron: external scrcpy window control panel -->
          <div v-else-if="screen.state.value.mode === 'scrcpy-window'" class="screen-wrapper scrcpy-control-panel">
            <div v-if="screen.state.value.isConnected" class="control-section">
              <div class="control-status">
                <el-tag type="success" size="small">scrcpy 投屏已启动</el-tag>
                <span class="control-hint">独立窗口投屏，操控在此面板</span>
              </div>

              <div class="control-buttons">
                <button class="ctrl-btn" title="返回" @click="sendKeyEvent('BACK')">
                  <el-icon><Back /></el-icon><span>返回</span>
                </button>
                <button class="ctrl-btn" title="桌面" @click="sendKeyEvent('HOME')">
                  <el-icon><HomeFilled /></el-icon><span>桌面</span>
                </button>
                <button class="ctrl-btn" title="任务窗" @click="sendKeyEvent('APP_SWITCH')">
                  <el-icon><Grid /></el-icon><span>任务</span>
                </button>
              </div>

              <div class="control-buttons">
                <button class="ctrl-btn small" title="音量+" @click="screen.sendKey(24)">
                  <span>Vol+</span>
                </button>
                <button class="ctrl-btn small" title="音量-" @click="screen.sendKey(25)">
                  <span>Vol-</span>
                </button>
                <button class="ctrl-btn small" title="电源" @click="screen.sendKey(26)">
                  <span>电源</span>
                </button>
              </div>

              <div class="control-actions">
                <el-button :icon="Camera" :loading="screenshotLoading === deviceStore.activeDevice.udid" size="small" @click="takeScreenshot">截图</el-button>
              </div>

              <el-input
                v-model="deviceTextInput"
                placeholder="输入文字发送到设备"
                size="small"
                @keyup.enter="sendDeviceText"
                class="control-input"
              >
                <template #append>
                  <el-button @click="sendDeviceText">发送</el-button>
                </template>
              </el-input>

              <el-button type="danger" size="small" @click="screen.disconnect()">停止投屏</el-button>
            </div>
            <div v-else class="control-section">
              <div class="control-status">
                <el-tag type="info" size="small">投屏未启动</el-tag>
              </div>
              <el-button type="primary" size="default" @click="connectScreen(deviceStore.activeDevice)">启动投屏</el-button>
            </div>
          </div>

          <!-- Embedded stream -->
          <div v-else class="screen-wrapper">
            <template v-if="isEmbeddedVideoStream">
              <video
                :ref="screen.setVideo"
                class="screen-video"
                :style="{ aspectRatio: screenAspectRatio }"
                muted
                autoplay
                playsinline
              />
              <div
                class="screen-input-overlay"
                tabindex="0"
                @pointerdown="handlePointerDown"
                @pointermove="handlePointerMove"
                @pointerup="handlePointerUp"
                @pointercancel="handlePointerCancel"
                @keydown="handleScreenKeyDown"
                @paste="handleScreenPaste"
              />
            </template>
            <template v-else-if="isScrcpyWebCodecsStream">
              <div :ref="screen.setYumeHost" class="screen-yume-host" />
              <div
                class="screen-input-overlay"
                tabindex="0"
                @pointerdown="handlePointerDown"
                @pointermove="handlePointerMove"
                @pointerup="handlePointerUp"
                @pointercancel="handlePointerCancel"
                @keydown="handleScreenKeyDown"
                @paste="handleScreenPaste"
              />
            </template>
            <canvas
              v-else
              id="screen-canvas"
              :ref="screen.setCanvas"
              class="screen-canvas"
              :style="{ background: '#000', aspectRatio: screenAspectRatio }"
              tabindex="0"
              @pointerdown="handlePointerDown"
              @pointermove="handlePointerMove"
              @pointerup="handlePointerUp"
              @pointercancel="handlePointerCancel"
              @keydown="handleScreenKeyDown"
              @paste="handleScreenPaste"
            />
          </div>
        </div>

        <!-- Android nav bar -->
        <div v-if="screen.state.value.mode !== 'scrcpy-window' && deviceStore.activeDevice?.platform !== 'ios'" class="android-nav-bar">
          <button class="android-nav-button" title="返回" :disabled="!deviceStore.activeDevice" @click="sendKeyEvent('BACK')">
            <el-icon><Back /></el-icon>
          </button>
          <button class="android-nav-button" title="桌面" :disabled="!deviceStore.activeDevice" @click="sendKeyEvent('HOME')">
            <el-icon><HomeFilled /></el-icon>
          </button>
          <button class="android-nav-button" title="任务窗" :disabled="!deviceStore.activeDevice" @click="sendKeyEvent('APP_SWITCH')">
            <el-icon><Grid /></el-icon>
          </button>
        </div>

        <!-- iOS nav bar -->
        <div v-if="screen.state.value.isConnected && deviceStore.activeDevice?.platform === 'ios'" class="android-nav-bar ios-nav-bar">
          <button class="android-nav-button" title="Home" :disabled="!deviceStore.activeDevice" @click="sendKeyEvent('HOME')">
            <el-icon><HomeFilled /></el-icon>
          </button>
        </div>

        <el-alert v-if="screen.state.value.notice" class="screen-alert" :title="screen.state.value.notice" type="warning" show-icon />

        <div v-if="latestScreenshot && deviceStore.activeDevice?.platform !== 'ios'" class="screenshot-strip">
          <img :src="getAssetUrl(latestScreenshot.url)" alt="截图" />
        </div>
      </div>
    </div>
  </div>

  </template>

<style scoped>
.page-shell {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
  background: var(--bg-primary);
}

/* Top Bar */
.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  height: 40px;
  padding: 0 16px;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-sidebar);
  color: var(--text-primary);
  flex-shrink: 0;
}

.device-info {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  font-size: 12px;
}

.device-info .label {
  color: var(--text-muted);
  font-weight: 500;
}

.device-info .value {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  color: var(--text-primary);
  font-weight: 500;
}

.device-info .value.empty {
  color: var(--text-muted);
  font-weight: 400;
}

.topbar-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
}

/* Workspace */
.workspace {
  display: flex;
  flex: 1;
  min-width: 0;
  overflow: hidden;
}

/* Activity Bar */
.activity-bar {
  display: flex;
  flex-direction: column;
  gap: 4px;
  width: 48px;
  padding: 8px 0;
  background: var(--bg-nav);
  flex-shrink: 0;
}

.activity-item {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 48px;
  height: 48px;
  border: 0;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  position: relative;
}

.activity-item:hover {
  color: var(--text-primary);
}

.activity-item.active {
  color: var(--accent);
}

.activity-item.active::before {
  content: '';
  position: absolute;
  left: 0;
  top: 8px;
  bottom: 8px;
  width: 2px;
  background: var(--accent);
}

.activity-spacer {
  flex: 1;
}

/* Left Sidebar */
.left-sidebar {
  display: flex;
  flex-direction: column;
  width: clamp(180px, 22vw, 220px);
  border-right: 1px solid var(--border-color);
  background: var(--bg-sidebar);
  color: var(--text-primary);
  flex-shrink: 0;
  transition: width 0.2s ease, margin-left 0.2s ease;
  overflow: hidden;
}

.left-sidebar.collapsed {
  width: 0;
  margin-left: 0;
  border-right: 0;
}

.sidebar-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 36px;
  padding: 0 12px;
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: var(--text-secondary);
}

.sidebar-title {
  user-select: none;
}

.sidebar-close {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border: 0;
  border-radius: 4px;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
}

.sidebar-close:hover {
  background: var(--bg-tertiary);
  color: var(--text-primary);
}

.sidebar-body {
  flex: 1;
  overflow: auto;
  padding: 4px 0;
}

.sidebar-footer {
  display: flex;
  flex-direction: column;
  gap: 8px;
  flex-shrink: 0;
  padding: 8px;
  border-top: 1px solid var(--border-color);
  background: var(--bg-sidebar);
}

.sidebar-section-title {
  padding: 6px 12px;
  font-size: 11px;
  font-weight: 600;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.sidebar-section-title.compact {
  padding: 2px 0;
}

/* Script toolbar */
.script-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-secondary);
  flex-shrink: 0;
}

.toolbar-title {
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.8px;
  color: var(--text-muted);
  flex: 1;
}

.toolbar-actions {
  display: flex;
  align-items: center;
  gap: 2px;
}

.toolbar-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border: 0;
  border-radius: 4px;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  padding: 0;
}

.toolbar-btn:hover {
  background: var(--bg-tertiary);
  color: var(--text-primary);
}

.root-create-row {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
  background: var(--bg-secondary);
}

.root-create-row .expand-arrow {
  width: 16px;
  height: 16px;
  visibility: hidden;
}

.root-create-row .inline-input {
  flex: 1;
  border: 1px solid var(--el-color-primary);
  border-radius: 3px;
  padding: 2px 6px;
  height: 22px;
  font-size: 13px;
  background: var(--el-bg-color);
  color: var(--el-text-color-primary);
  outline: none;
  min-width: 80px;
}

/* File tree */
.file-tree {
  display: flex;
  flex-direction: column;
}

.file-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  font-size: 13px;
  color: var(--text-primary);
  cursor: pointer;
  user-select: none;
}

.file-item:hover {
  background: var(--bg-tertiary);
}

.file-item.active {
  background: var(--accent-subtle);
  color: var(--accent);
}

.file-icon {
  flex-shrink: 0;
  color: var(--text-muted);
}

.file-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-delete {
  display: none;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  border: 0;
  border-radius: 4px;
  background: transparent;
  color: var(--danger);
  cursor: pointer;
  flex-shrink: 0;
}

.file-item:hover .file-delete {
  display: flex;
}

.file-tree-empty {
  padding: 16px;
  color: var(--text-muted);
  font-size: 12px;
  text-align: center;
}

/* Device mini list */
.device-list-mini {
  display: flex;
  flex-direction: column;
}

.device-mini-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  cursor: pointer;
  color: var(--text-primary);
}

.device-mini-item:hover {
  background: var(--bg-tertiary);
}

.device-mini-item.active {
  background: var(--bg-tertiary);
}

.device-mini-info {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
  gap: 2px;
}

.device-mini-name {
  font-size: 12px;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.device-mini-id {
  font-size: 10px;
  color: var(--text-muted);
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* Screen controls */
.screen-controls {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 8px 12px;
}

.screen-info {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 12px;
  color: var(--text-muted);
}

.visual-actions {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding-top: 4px;
  border-top: 1px solid var(--border-color);
}

.basic-record-row {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 6px;
}

.basic-record-row :deep(.el-button) {
  min-width: 0;
  margin-left: 0;
}

.visual-record-hint {
  padding: 6px 8px;
  border: 1px solid var(--accent);
  border-radius: 4px;
  background: var(--accent-subtle);
  color: var(--accent);
  font-size: 11px;
  line-height: 1.4;
}

.element-record-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 8px;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  background: var(--bg-secondary);
}

.element-record-card.active {
  border-color: var(--accent);
  background: var(--accent-subtle);
}

.element-record-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  color: var(--text-primary);
  font-size: 12px;
  font-weight: 600;
}

.element-record-hint {
  color: var(--text-muted);
  font-size: 11px;
  line-height: 1.4;
}

.visual-action-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 32px;
  gap: 6px;
}

.template-picker {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 8px;
  align-items: center;
  min-height: 32px;
  padding: 6px 8px;
  border: 1px dashed var(--border-color);
  border-radius: 6px;
  color: var(--text-primary);
  cursor: pointer;
  font-size: 12px;
}

.template-picker:hover {
  border-color: var(--accent);
  background: var(--bg-tertiary);
}

.template-picker span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.template-picker input {
  display: none;
}

.threshold-row {
  display: grid;
  grid-template-columns: 34px minmax(0, 1fr);
  align-items: center;
  gap: 8px;
  color: var(--text-muted);
  font-size: 12px;
}

/* Editor Area */
.editor-area {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
  background: var(--bg-primary);
}

/* Tab Bar */
.tab-bar {
  display: flex;
  height: 36px;
  background: var(--bg-tertiary);
  border-bottom: 1px solid var(--border-color);
  overflow-x: auto;
  flex-shrink: 0;
}

.tab-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 0 12px;
  min-width: 120px;
  max-width: 200px;
  height: 36px;
  background: var(--bg-tertiary);
  border-right: 1px solid var(--border-color);
  color: var(--text-secondary);
  font-size: 12px;
  cursor: pointer;
  user-select: none;
  white-space: nowrap;
}

.tab-item:hover {
  background: var(--bg-tertiary);
  color: var(--text-primary);
}

.tab-item.active {
  background: var(--bg-primary);
  color: var(--accent);
  border-top: 1px solid var(--accent);
}

.tab-item span {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
}

.tab-close {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  border: 0;
  border-radius: 4px;
  background: transparent;
  color: var(--text-muted);
  font-size: 14px;
  cursor: pointer;
  line-height: 1;
}

.tab-close:hover {
  background: var(--bg-tertiary);
  color: var(--text-primary);
}

/* Editor Content */
.editor-content {
  flex: 1;
  overflow: auto;
  min-height: 0;
}

/* Script Editor Wrapper */
.script-editor-wrapper {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.script-editor-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 8px 12px;
  background: var(--bg-sidebar);
  border-bottom: 1px solid var(--border-color);
  flex-shrink: 0;
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.toolbar-right {
  display: flex;
  align-items: center;
  gap: 4px;
}

.python-env-select {
  width: 180px;
}

.font-size-label {
  font-size: 12px;
  color: var(--text-muted);
  min-width: 36px;
  text-align: center;
}

.editor-container {
  display: flex;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.line-numbers {
  flex-shrink: 0;
  padding: 12px 8px;
  background: var(--bg-tertiary);
  border-right: 1px solid var(--border-color);
  color: var(--text-muted);
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  line-height: 1.6;
  text-align: right;
  user-select: none;
  overflow: hidden;
}

.line-number {
  min-width: 24px;
}

.script-editor {
  flex: 1;
  min-height: 0;
  width: 100%;
  padding: 12px 16px;
  background: var(--bg-code);
  color: var(--text-primary);
  border: 0;
  resize: none;
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 13px;
  line-height: 1.6;
  outline: none;
}

.script-editor.with-line-numbers {
  padding-left: 12px;
}

.script-editor.word-wrap {
  white-space: pre-wrap;
  word-wrap: break-word;
}

/* Run Output */
.run-output {
  max-height: 200px;
  overflow: auto;
  padding: 8px 16px;
  background: var(--bg-secondary);
  border-top: 1px solid var(--border-color);
  flex-shrink: 0;
}

.output-stdout,
.output-stderr {
  margin: 0;
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
}

.output-stdout {
  color: var(--text-primary);
}

.output-stderr {
  color: var(--danger);
}

/* VSCode Idle Page */
.idle-page {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  padding: 40px;
  color: var(--text-primary);
}

.idle-logo {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
  margin-bottom: 48px;
}

.idle-logo h1 {
  margin: 0;
  font-size: 24px;
  font-weight: 400;
  color: var(--text-primary);
}

.idle-logo .el-icon {
  color: var(--accent);
}

.idle-sections {
  display: grid;
  grid-template-columns: repeat(3, minmax(160px, 240px));
  gap: 32px;
  max-width: 100%;
}

.idle-section h3 {
  margin: 0 0 12px;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-secondary);
}

.idle-section ul {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.idle-section li {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border-radius: 4px;
  font-size: 13px;
  color: var(--accent);
  cursor: pointer;
}

.idle-section li:hover {
  background: var(--bg-tertiary);
}

.idle-section li.empty {
  color: var(--text-muted);
  cursor: default;
}

.idle-section li.empty:hover {
  background: transparent;
}

.idle-section li span {
  color: var(--text-primary);
}

/* Right Panel */
.right-panel {
  display: flex;
  flex-direction: column;
  width: clamp(320px, 38vw, 480px);
  flex-shrink: 0;
  border-left: 1px solid var(--border-color);
  background: var(--bg-sidebar);
  padding: 8px;
  gap: 8px;
}

.panel-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-shrink: 0;
  min-height: 24px;
}

.screen-meta {
  display: flex;
  align-items: center;
  gap: 6px;
}

.frame-count {
  color: var(--text-muted);
  font-size: 11px;
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
}

.screen-container {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 0;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  background: var(--bg-code);
  overflow: hidden;
}

.screen-loading,
.screen-empty,
.screen-error {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  color: var(--text-muted);
  font-size: 13px;
}

.screen-wrapper {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 100%;
  padding: 8px;
}

.native-screen-wrapper {
  padding: 0;
}

.native-screen-host {
  position: relative;
  width: 100%;
  height: 100%;
  min-height: 220px;
  overflow: hidden;
  background: #000;
  cursor: crosshair;
  outline: none;
  touch-action: none;
}

.native-screen-overlay {
  position: absolute;
  inset: 0;
  z-index: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  color: var(--text-muted);
  background: rgba(0, 0, 0, 0.72);
  pointer-events: none;
}

.native-screen-overlay.error {
  color: var(--el-color-danger);
}

/* Electron scrcpy control panel */
.scrcpy-control-panel {
  align-items: stretch;
  justify-content: flex-start;
}

.control-section {
  display: flex;
  flex-direction: column;
  gap: 12px;
  width: 100%;
  padding: 12px;
}

.control-status {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.control-hint {
  font-size: 11px;
  color: var(--text-muted);
}

.control-buttons {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.ctrl-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  min-width: 64px;
  height: 36px;
  padding: 0 12px;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  background: var(--bg-secondary);
  color: var(--text-primary);
  cursor: pointer;
  font-size: 13px;
}

.ctrl-btn:hover {
  background: var(--bg-tertiary);
  border-color: var(--accent);
}

.ctrl-btn.small {
  min-width: 48px;
  height: 32px;
  padding: 0 8px;
  font-size: 12px;
}

.control-actions {
  display: flex;
  gap: 8px;
}

.control-input {
  width: 100%;
}

.ios-screenshot-wrapper {
  padding: 12px;
}

.ios-screenshot-canvas {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}

.ios-screenshot-canvas img {
  max-width: 100%;
  max-height: 100%;
  display: block;
  object-fit: contain;
  cursor: crosshair;
  user-select: none;
  touch-action: none;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  background: #000;
}

.screen-canvas {
  max-width: 100%;
  max-height: 100%;
  display: block;
  cursor: crosshair;
  touch-action: none;
}

.screen-video {
  display: block;
  max-width: 100%;
  max-height: 100%;
  width: auto;
  height: 100%;
  object-fit: contain;
  background: #000;
}

.screen-yume-host {
  display: flex;
  width: 100%;
  height: 100%;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}

.screen-yume-host :deep(canvas) {
  max-width: 100%;
  max-height: 100%;
  display: block;
  cursor: crosshair;
  touch-action: none;
}

.screen-input-overlay {
  position: absolute;
  inset: 8px;
  z-index: 2;
  cursor: crosshair;
  outline: none;
  touch-action: none;
}

.android-nav-bar {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  align-items: center;
  gap: 8px;
  height: 44px;
  padding: 6px 14px;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  background: var(--bg-nav);
  flex-shrink: 0;
}

.android-nav-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 30px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
}

.android-nav-button:hover:not(:disabled) {
  background: var(--bg-tertiary);
  color: var(--text-primary);
}

.android-nav-button:disabled {
  cursor: not-allowed;
  opacity: 0.35;
}

.screen-alert {
  flex-shrink: 0;
}

.screenshot-strip {
  padding: 6px;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  background: var(--bg-primary);
  flex-shrink: 0;
}

.screenshot-strip img {
  display: block;
  width: 100%;
  max-height: 100px;
  object-fit: contain;
  border-radius: 4px;
}

@media (max-width: 1100px) {
  .idle-sections {
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    width: min(100%, 620px);
  }
}

@media (max-width: 900px) {
  .workspace {
    display: grid;
    grid-template-columns: 48px minmax(0, 1fr);
    grid-template-rows: minmax(0, 1fr) minmax(220px, 34vh);
  }

  .activity-bar {
    grid-row: 1 / 3;
  }

  .left-sidebar {
    width: min(220px, 34vw);
  }

  .editor-area {
    min-height: 0;
  }

  .right-panel {
    grid-column: 2;
    grid-row: 2;
    width: auto;
    min-width: 0;
    border-top: 1px solid var(--border-color);
    border-left: 0;
  }
}

@media (max-width: 720px) {
  .topbar {
    height: auto;
    min-height: 40px;
    flex-wrap: wrap;
    padding: 6px 10px;
  }

  .device-info {
    min-width: 0;
  }

  .device-info .value {
    min-width: 0;
    flex-wrap: wrap;
  }

  .left-sidebar {
    width: 0;
    border-right: 0;
  }
}
</style>
