<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch, inject } from 'vue'
import {
  ArrowDown,
  Cellphone,
  Close,
  Refresh,
  UploadFilled,
  VideoPlay,
  Document,
  Loading,
  Plus,
  User,
  DataAnalysis,
  Delete,
  MagicStick,
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createImportedTestCase,
  batchUpdateImportedTestCases,
  createLoginAccount,
  deleteLoginAccount,
  deleteTestPlan,
  deleteImportedTestCase,
  fetchTestPlan,
  fetchTestPlans,
  fetchLoginAccounts,
  updateLoginAccount,
  fetchTestPlanReport,
  exportTestPlanReport,
  fetchPendingInputRequests,
  respondToInputRequest,
  cancelInputRequest,
  cancelTestRun,
  importTestPlan,
  generateFromRequirement,
  fetchExecutionDetailReport,
  resumeTestRun,
  runImportedTestCaseStream,
  runImportedTestPlanStream,
  getAssetUrl,
  createTestCaseFolder,
  listTestCaseFolders,
  updateTestCaseFolder,
  deleteTestCaseFolder,
  batchMoveCasesToFolder,
  buildAutoGLMPlan,
  type AutoGLMPlanResponse,
  type BatchUpdateCasesRequest,
  type UserInputRequest,
  type DeviceInfo,
  type ExecutionDetailReport,
  type ImportedTestCase,
  type LoginAccount,
  type TestCaseFolder,
  type TestCaseRunStreamEvent,
  type TestPlanListItem,
  type TestPlanProject,
  type TestPlanReport,
} from '../api'
import { useDeviceStore } from '../stores'
import { type ScreenStreamHandle } from '../composables'
import { useCaseRunLogs, usePolling } from '../composables'
import {
  classifyMobileGesture,
  shouldStartLiveTouch,
  shouldUseContinuousTouch,
  TAP_DISTANCE_PX,
  normalizedGestureDuration,
} from '../utils/mobileGesture'
import TestCaseExecutionReport from '../components/test/TestCaseExecutionReport.vue'
import CaseStepLog from '../components/test/CaseStepLog.vue'

// Store
const deviceStore = useDeviceStore()

// Screen stream — shared singleton provided by App.vue
const screen = inject<ScreenStreamHandle>('screenStream')!
const electronAPI = typeof window !== 'undefined' ? (window as any).electronAPI : undefined
const isElectron = Boolean(electronAPI?.isElectron)
const isEmbeddedVideoStream = computed(() =>
  screen.state.value.provider === 'scrcpy-ffmpeg-fmp4' || screen.state.value.mimeType === 'video/mp4',
)
const isScrcpyWebCodecsStream = computed(() =>
  // Only the dedicated yume provider renders into yumeHost. The backend
  // maps scrcpy-webcodecs to scrcpy-h264, which must stay on the canvas path.
  screen.state.value.provider === 'scrcpy-webcodecs' ||
  screen.state.value.mimeType === 'application/x-scrcpy-webcodecs',
)
const screenAspectRatio = computed(() => {
  const { width, height } = screen.state.value
  return width > 0 && height > 0 ? `${width} / ${height}` : undefined
})

// Local state
const testPlans = ref<TestPlanListItem[]>([])
const selectedPlan = ref<TestPlanProject | null>(null)
const testPlanLoading = ref(false)
const importBusy = ref(false)

// Folder (document) state
const selectedFolderId = ref<number | null>(null)  // null = show all
const showCreateFolderDialog = ref(false)
const newFolderName = ref('')
const newFolderSummary = ref('')
const showMoveDialog = ref(false)
const moveTargetFolderId = ref<number | null>(null)
const batchRunning = ref(false)
const batchRunId = ref<string | null>(null)
const batchController = ref<AbortController | null>(null)
const caseControllers = new Map<number, AbortController>()
const caseRunIds = new Map<number, string>()
const projectName = ref('')
const selectedExcelFile = ref<File | null>(null)
const manualCaseDialogVisible = ref(false)
const manualCaseBusy = ref(false)
const manualCaseRunAfterSave = ref(true)
const loginAccounts = ref<LoginAccount[]>([])
const loginAccountDialogVisible = ref(false)
const loginAccountBusy = ref(false)

// AI generation
const aiGenBusy = ref(false)
const aiGenPhase = ref<'idle' | 'extracting' | 'generating' | 'refining' | 'saving' | 'done'>('idle')
const aiGenProjectName = ref('')
const aiGenTargetApp = ref('乐有家测试版')
const aiGenRequirementFile = ref<File | null>(null)
const aiGenErrorMessage = ref('')

const aiGenPhaseStepIndex = computed(() => {
  const map: Record<string, number> = { idle: 0, extracting: 0, generating: 1, refining: 2, saving: 3, done: 4 }
  return map[aiGenPhase.value] ?? 0
})

const aiGenPhaseLabel = computed(() => {
  const map: Record<string, string> = { extracting: '提取文档', generating: '生成用例', refining: '优化步骤', saving: '保存用例' }
  return map[aiGenPhase.value] || '处理中'
})

// ── Touch handling for phone-screen control ──────────────────────────────
const pointerStart = ref<{ x: number; y: number; at: number } | null>(null)
let liveTouchActive = false
let lastLiveTouchMoveAt = 0
const LIVE_TOUCH_MOVE_INTERVAL_MS = 16

const PHONE_KEYCODE_MAP: Record<string, number> = {
  Backspace: 67,
  Enter: 66,
  Tab: 61,
  Escape: 111,
}

const PHONE_NAV_KEY_MAP: Record<string, number> = {
  BACK: 4,
  HOME: 3,
  APP_SWITCH: 187,
}

function hasLiveScrcpyControl(): boolean {
  return (
    screen.state.value.controlMode === 'live' &&
    screen.state.value.controlConnected
  )
}

function handlePhonePointerDown(event: PointerEvent) {
  const point = screen.toDevicePoint(event)
  if (!point) return
  event.preventDefault()
  const target = event.currentTarget as HTMLElement
  target.focus()
  target.setPointerCapture(event.pointerId)
  pointerStart.value = { ...point, at: performance.now() }
  liveTouchActive = false
  lastLiveTouchMoveAt = 0

  if (hasLiveScrcpyControl()) {
    liveTouchActive = screen.sendTouchDown(point.x, point.y)
  }
}

function handlePhonePointerMove(event: PointerEvent) {
  const start = pointerStart.value
  if (!start) return
  const point = screen.toDevicePoint(event)
  if (!point) return
  event.preventDefault()
  const now = performance.now()
  const distance = Math.hypot(point.x - start.x, point.y - start.y)

  if (!liveTouchActive) {
    if (hasLiveScrcpyControl()) {
      if (!shouldStartLiveTouch(distance)) return
      liveTouchActive = screen.sendTouchDown(start.x, start.y)
      if (!liveTouchActive) return
      lastLiveTouchMoveAt = 0
    } else {
      const duration = normalizedGestureDuration(start.at, now)
      if (!shouldStartLiveTouch(distance)) return
      if (!shouldUseContinuousTouch({ distance, durationMs: duration, pointerType: event.pointerType })) return
      liveTouchActive = screen.sendTouchDown(start.x, start.y)
      if (!liveTouchActive) return
      lastLiveTouchMoveAt = 0
    }
  }

  if (now - lastLiveTouchMoveAt < LIVE_TOUCH_MOVE_INTERVAL_MS) return
  lastLiveTouchMoveAt = now
  screen.sendTouchMove(point.x, point.y)
}

function handlePhonePointerUp(event: PointerEvent) {
  const start = pointerStart.value
  const end = screen.toDevicePoint(event)
  const usedLiveTouch = liveTouchActive
  liveTouchActive = false
  pointerStart.value = null
  if (!start || !end) return
  event.preventDefault()

  if (usedLiveTouch) {
    screen.sendTouchUp(end.x, end.y)
    if (hasLiveScrcpyControl()) return
  }

  // ADB fallback path
  const distance = Math.hypot(end.x - start.x, end.y - start.y)
  const duration = normalizedGestureDuration(start.at, performance.now())
  const gesture = classifyMobileGesture({ distance, durationMs: duration })

  if (gesture === 'tap') {
    if (!usedLiveTouch) {
      screen.sendControl({ type: 'tap', x: end.x, y: end.y })
    }
    return
  }

  if (gesture === 'long_press') {
    if (!usedLiveTouch) {
      screen.sendControl({ type: 'long_press', x: end.x, y: end.y, duration_ms: duration })
    }
    return
  }

  if (gesture === 'drag') {
    const pressDuration = Math.min(200, duration - 100)
    const dragDuration = Math.max(100, duration - pressDuration)
    if (!usedLiveTouch) {
      screen.sendControl({
        type: 'swipe',
        x1: start.x,
        y1: start.y,
        x2: end.x,
        y2: end.y,
        duration_ms: dragDuration,
        press_duration_ms: pressDuration,
      })
    }
    return
  }

  // swipe fallback
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
}

function handlePhonePointerCancel(event?: PointerEvent) {
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

function handlePhoneKeyDown(event: KeyboardEvent) {
  if (!deviceStore.activeDevice || event.ctrlKey || event.metaKey || event.altKey) return

  if (event.key.length === 1) {
    event.preventDefault()
    screen.sendControl({ type: 'text', text: event.key })
    return
  }

  const keycode = PHONE_KEYCODE_MAP[event.key]
  if (keycode) {
    event.preventDefault()
    screen.sendKey(keycode)
  }
}

function sendPhoneNavKey(key: string) {
  const keycode = PHONE_NAV_KEY_MAP[key]
  if (keycode) {
    screen.sendKey(keycode)
  }
}

// Batch edit
const selectedCaseRows = ref<ImportedTestCase[]>([])
const batchEditDialogVisible = ref(false)
const batchEditBusy = ref(false)
const batchEditForm = ref({
  system_name: '',
  module: '',
  target_app: '',
  test_module: '',
})
const batchEditClear = ref({
  system_name: false,
  module: false,
  target_app: false,
  test_module: false,
})

interface ManualCaseForm {
  case_name: string
  folder_id: number | null
  system_name: string
  module: string
  precondition: string
  stepsText: string
  expected_result: string
  priority: string
  target_app: string
  test_module: string
}

interface LoginAccountForm {
  id: number | null
  platform: string
  label: string
  login_id: string
  password: string
  note: string
  use_for_autoglm: boolean
}

const loginAccountForm = ref<LoginAccountForm>({
  id: null,
  platform: '乐有家',
  label: '',
  login_id: '',
  password: '',
  note: '',
  use_for_autoglm: true,
})

const manualCaseForm = ref<ManualCaseForm>({
  case_name: '',
  folder_id: null,
  system_name: '',
  module: '',
  precondition: '',
  stepsText: '',
  expected_result: '',
  priority: '',
  target_app: '乐有家测试版',
  test_module: '',
})

// User input dialog
const userInputDialogVisible = ref(false)
const currentInputRequest = ref<UserInputRequest | null>(null)
const userInputValue = ref('')
const inputPollTimer = ref<number | null>(null)

// Test report
const planReportDialogVisible = ref(false)
const executionReportDialogVisible = ref(false)
const selectedExecutionId = ref<number | null>(null)
const testPlanReport = ref<TestPlanReport | null>(null)
const reportLoading = ref(false)

// Expanded case tracking
const expandedCaseId = ref<number | null>(null)
const expandedCaseIds = ref<number[]>([])
const expandedExecutionDetail = ref<ExecutionDetailReport | null>(null)
const expandedLoading = ref(false)

// Checkpoint plan state
const checkpointPlan = ref<AutoGLMPlanResponse | null>(null)
const checkpointPlanBusy = ref(false)
const checkpointPlanCaseId = ref<number | null>(null)

async function loadCheckpointPlan(caseId: number, caseName: string, targetApp: string, steps: string[], expectedResult: string) {
  if (checkpointPlanCaseId.value === caseId && checkpointPlan.value) return
  checkpointPlanBusy.value = true
  checkpointPlanCaseId.value = caseId
  try {
    checkpointPlan.value = await buildAutoGLMPlan({
      case_id: caseId,
      target_app: targetApp || '未知应用',
      platform: deviceStore.activeDevice?.platform || 'android',
      steps,
      expected_result: expectedResult,
    })
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '加载 Checkpoint 计划失败')
    checkpointPlan.value = null
  } finally {
    checkpointPlanBusy.value = false
  }
}

/** Convert ExecutionDetailReport action_summary + screenshots to log events for CaseStepLog */
const expandedExecutionEvents = computed<TestCaseRunStreamEvent[]>(() => {
  const detail = expandedExecutionDetail.value
  if (!detail) return []
  const events: TestCaseRunStreamEvent[] = []

  // Add header event
  events.push({
    event: 'log',
    type: 'case_task_plan',
    phase: 'device_check',
    timestamp: detail.started_at ?? undefined,
    message: `设备: ${detail.device_udid || '未知'}` + (detail.trace_id ? ` ｜ Trace: ${detail.trace_id.slice(0, 8)}...` : ''),
    trace_id: detail.trace_id ?? undefined,
  })

  // Add action events
  for (const action of detail.action_summary) {
    events.push({
      event: action.success ? 'log' : 'error',
      type: 'action_executed',
      phase: 'execution',
      timestamp: action.timestamp ?? undefined,
      message: action.message,
      step: action.step,
      action_type: action.action_type,
      success: action.success,
      screenshot_url: action.screenshot_url ?? undefined,
      action_params: (action as any).action_params,
    })
  }

  // Add result event
  events.push({
    event: 'result',
    type: 'result',
    phase: 'report',
    message: detail.result_note || detail.result || '',
    run_result: detail.result as TestCaseRunStreamEvent['run_result'],
    duration_ms: detail.duration_ms,
    trace_id: detail.trace_id ?? undefined,
  })

  return events
})

const {
  runningCaseId,
  hasRunningCase,
  startCaseLog,
  appendCaseLog,
  finishCaseLog,
  finishAllCaseLogs,
  isCaseRunning,
  isCaseWaitingForUser,
  getCaseLogs,
  getCasePhaseLogs,
  getVisiblePhases,
} = useCaseRunLogs()
const resumingCaseIds = ref<Record<number, boolean>>({})
const batchProgress = ref({
  totalCases: 0,
  completedCases: 0,
  currentCaseId: null as number | null,
  currentCaseName: '',
})

function getExecutionIdFromReport(caseId: number): number | null {
  if (!testPlanReport.value) return null
  const reportCase = testPlanReport.value.cases.find(c => c.case_id === caseId)
  return reportCase?.latest_execution_id ?? null
}

function formatLogTimestamp(ts: string | null | undefined): string {
  if (!ts) return ''
  try {
    const date = new Date(ts)
    return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  } catch {
    return ''
  }
}

function getActionIcon(actionType: string): string {
  const iconMap: Record<string, string> = {
    'tap': '👆',
    'click': '👆',
    'swipe': '👆',
    'long_press': '👇',
    'type': '⌨️',
    'back': '◀️',
    'home': '🏠',
    'finish': '✅',
    'Wait': '⏳',
    'Note': '📝',
    'Call_API': '🔌',
  }
  return iconMap[actionType] || '▶️'
}

function getScreenshotUrl(step: number): string | null {
  if (!expandedExecutionDetail.value) return null
  // First try to get screenshot from action_summary (new enhanced format)
  const action = expandedExecutionDetail.value.action_summary.find(a => a.step === step)
  if (action?.screenshot_url) return action.screenshot_url
  // Fallback to screenshots array
  const screenshot = expandedExecutionDetail.value.screenshots.find(s => s.step === step)
  return screenshot?.url ?? null
}

const activeRunnableDevice = computed(() => {
  const device = deviceStore.activeDevice
  return device?.status === 'online' ? device : null
})
const activeDeviceUdid = computed(() => activeRunnableDevice.value?.udid)
const activeDevicePlatform = computed(() => activeRunnableDevice.value?.platform)
const platformOptions = ['乐有家', '乐有家线下版', '乐办公', '乐办公测试环境', '微信', 'QQ', '手机安装密码']


function statusType(status: string) {
  if (status === 'online') return 'success'
  if (status === 'offline') return 'info'
  if (status === 'unauthorized') return 'warning'
  return 'danger'
}

function resultType(result: string) {
  if (result === 'passed') return 'success'
  if (result === 'failed') return 'danger'
  if (result === 'running' || result === 'uncertain') return 'warning'
  return 'info'
}

function assertionBrief(row: TestPlanReport['cases'][number]) {
  const assertion = row.latest_assertion
  if (!assertion?.verdict) return '-'
  const confidence = typeof assertion.confidence === 'number'
    ? `${Math.round(assertion.confidence * 100)}%`
    : '-'
  return `${assertion.verdict} / ${confidence}`
}

const batchEditSystemNamePresets = computed(() => {
  const app = batchEditForm.value.target_app
  if (app === '乐有家测试版') return ['乐有家', '乐有家线下版']
  if (app === '乐办公测试版') return ['乐办公', '乐办公测试环境']
  if (app === '微信小程序') return ['微信']
  return []
})

const batchEditModulePresets = computed(() => {
  const app = batchEditForm.value.target_app
  if (app === '乐有家测试版') return ['找房', '学区', '搜索', '消息', '我的家']
  if (app === '乐办公测试版') return ['录客', '客源', '获客', '录盘', '经纪人']
  if (app === '微信小程序') return ['首页', '搜索', '详情']
  return []
})

const batchEditTestModulePresets = computed(() => {
  const app = batchEditForm.value.target_app
  if (app === '乐有家测试版') return ['AI找房', 'AI学区顾问', 'AI搜']
  if (app === '乐办公测试版') return ['录客', '客源', '获客', '录盘', '经纪人']
  if (app === '微信小程序') return ['乐有家体验版小程序']
  return []
})

function openBatchEditDialog() {
  batchEditForm.value = {
    system_name: '',
    module: '',
    target_app: '',
    test_module: '',
  }
  batchEditClear.value = {
    system_name: false,
    module: false,
    target_app: false,
    test_module: false,
  }
  batchEditDialogVisible.value = true
}

async function submitBatchEdit() {
  if (!selectedPlan.value) return
  if (selectedCaseRows.value.length === 0) {
    ElMessage.warning('请先选择要编辑的用例')
    return
  }
  batchEditBusy.value = true
  try {
    const payload: BatchUpdateCasesRequest = {
      case_ids: selectedCaseRows.value.map(c => c.id),
    }
    // 清空字段优先：勾选"清空"则发送空字符串，否则发送填写的值
    if (batchEditClear.value.system_name) payload.system_name = ''
    else if (batchEditForm.value.system_name) payload.system_name = batchEditForm.value.system_name
    if (batchEditClear.value.module) payload.module = ''
    else if (batchEditForm.value.module) payload.module = batchEditForm.value.module
    if (batchEditClear.value.target_app) payload.target_app = ''
    else if (batchEditForm.value.target_app) payload.target_app = batchEditForm.value.target_app
    if (batchEditClear.value.test_module) payload.test_module = ''
    else if (batchEditForm.value.test_module) payload.test_module = batchEditForm.value.test_module
    // 至少需要修改一个字段
    const hasAnyChange = payload.system_name !== undefined
      || payload.module !== undefined
      || payload.target_app !== undefined
      || payload.test_module !== undefined
    if (!hasAnyChange) {
      ElMessage.warning('请至少修改一个字段或勾选清空')
      batchEditBusy.value = false
      return
    }
    await batchUpdateImportedTestCases(selectedPlan.value.id, payload)
    batchEditDialogVisible.value = false
    selectedPlan.value = await fetchTestPlan(selectedPlan.value.id)
    selectedCaseRows.value = []
    ElMessage.success(`已批量更新 ${payload.case_ids.length} 条用例`)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '批量更新失败')
  } finally {
    batchEditBusy.value = false
  }
}

function handleCaseSelectionChange(rows: ImportedTestCase[]) {
  selectedCaseRows.value = rows
}

const systemNamePresets = computed(() => {
  const app = manualCaseForm.value.target_app
  if (app === '乐有家测试版') return ['乐有家', '乐有家线下版']
  if (app === '乐办公测试版') return ['乐办公', '乐办公测试环境']
  if (app === '微信小程序') return ['微信']
  return []
})

const modulePresets = computed(() => {
  const app = manualCaseForm.value.target_app
  if (app === '乐有家测试版') return ['找房', '学区', '搜索', '消息', '我的家']
  if (app === '乐办公测试版') return ['录客', '客源', '获客', '录盘', '经纪人']
  if (app === '微信小程序') return ['首页', '搜索', '详情']
  return []
})

const testModulePresets = computed(() => {
  const app = manualCaseForm.value.target_app
  if (app === '乐有家测试版') return ['AI找房', 'AI学区顾问', 'AI搜']
  if (app === '乐办公测试版') return ['录客', '客源', '获客', '录盘', '经纪人']
  if (app === '微信小程序') return ['乐有家体验版小程序']
  return []
})

function phaseLabel(phase: string) {
  const labels: Record<string, string> = {
    device_check: '设备检测',
    precondition: '前置条件',
    execution: 'AutoGLM 执行',
    report: '报告保存',
  }
  return labels[phase] || phase
}

function logEventClass(event: TestCaseRunStreamEvent) {
  return {
    error: event.event === 'error',
    result: event.event === 'result',
    waiting: event.event === 'need_user',
  }
}

function formatCaseSteps(steps: string[]) {
  return steps.map((step, index) => `${index + 1}. ${step}`).join('\n')
}

function parseManualSteps(raw: string) {
  return raw
    .split(/\r?\n/)
    .map(step => step.replace(/^\s*\d+[.、]\s*/, '').trim())
    .filter(Boolean)
}

// Device connection
function selectDevice(device: DeviceInfo) {
  if (device.status !== 'online') return
  connectScreen(device)
}

function requireRunnableDevice() {
  if (!deviceStore.activeDevice) {
    ElMessage.warning('请先选择在线设备')
    return null
  }
  if (deviceStore.activeDevice.status !== 'online') {
    ElMessage.warning('当前设备不在线，请重新连接或切换设备')
    return null
  }
  return deviceStore.activeDevice
}

function connectScreen(device: DeviceInfo) {
  if (device.status !== 'online') return
  if (
    screen.state.value.udid === device.udid &&
    (screen.state.value.isConnected || screen.state.value.isLoading)
  ) return
  deviceStore.setActiveDevice(device)
  screen.connect(device.udid, {
    platform: device.platform,
    provider: 'scrcpy-webcodecs',
    maxFps: isElectron ? 30 : 30,
    maxSize: isElectron ? 1280 : 960,
    useNativeScrcpySurface: isElectron,
    wdaUrl: device.wda_url ?? undefined,
    control: false,  // 只投屏不控制，节省性能
  })
}

function autoConnectActiveDevice() {
  const device = deviceStore.activeDevice
  if (!device || device.status !== 'online' || device.platform !== 'android') {
    if (screen.state.value.udid && device?.udid === screen.state.value.udid) {
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

async function refreshDevices() {
  await deviceStore.loadDevices(true)
  autoConnectActiveDevice()
}

// Test plans
async function loadTestPlans() {
  testPlanLoading.value = true
  try {
    testPlans.value = await fetchTestPlans()
    if (!selectedPlan.value && testPlans.value.length > 0) {
      await selectTestPlan(testPlans.value[0].id)
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '测试计划获取失败')
  } finally {
    testPlanLoading.value = false
  }
}

async function loadLoginAccounts() {
  try {
    loginAccounts.value = await fetchLoginAccounts()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '账号配置加载失败')
  }
}

function resetLoginAccountForm(platform = '乐有家') {
  loginAccountForm.value = {
    id: null,
    platform,
    label: '',
    login_id: '',
    password: '',
    note: '',
    use_for_autoglm: true,
  }
}

function openLoginAccountDialog(account?: LoginAccount) {
  if (account) {
    loginAccountForm.value = {
      id: account.id,
      platform: account.platform,
      label: account.label,
      login_id: account.login_id,
      password: '',
      note: account.note || '',
      use_for_autoglm: account.use_for_autoglm,
    }
  } else {
    resetLoginAccountForm()
  }
  loginAccountDialogVisible.value = true
}

async function saveLoginAccount() {
  const form = loginAccountForm.value
  if (!form.platform.trim() || !form.label.trim() || !form.login_id.trim()) {
    ElMessage.warning('请填写平台、名称和账号')
    return
  }
  if (!form.id && !form.password.trim()) {
    ElMessage.warning('新增账号时请填写密码')
    return
  }
  loginAccountBusy.value = true
  try {
    const payload = {
      platform: form.platform.trim(),
      label: form.label.trim(),
      login_id: form.login_id.trim(),
      password: form.password.trim(),
      note: form.note.trim() || null,
      use_for_autoglm: form.use_for_autoglm,
    }
    if (form.id) {
      await updateLoginAccount(form.id, payload)
      ElMessage.success('账号配置已更新')
    } else {
      await createLoginAccount(payload)
      ElMessage.success('账号配置已新增')
    }
    loginAccountDialogVisible.value = false
    await loadLoginAccounts()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '账号配置保存失败')
  } finally {
    loginAccountBusy.value = false
  }
}

async function removeLoginAccount(account: LoginAccount) {
  try {
    await ElMessageBox.confirm(`确认删除账号配置「${account.label}」？`, '删除账号配置', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
    await deleteLoginAccount(account.id)
    await loadLoginAccounts()
    ElMessage.success('账号配置已删除')
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error(error instanceof Error ? error.message : '删除失败')
    }
  }
}

async function removeTestPlan(plan: TestPlanListItem) {
  try {
    await ElMessageBox.confirm(
      `删除测试计划「${plan.name}」将同时删除其下所有用例和执行记录，确认删除？`,
      '删除测试计划',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
    await deleteTestPlan(plan.id)
    if (selectedPlan.value?.id === plan.id) {
      selectedPlan.value = null
    }
    await loadTestPlans()
    ElMessage.success('测试计划已删除')
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error(error instanceof Error ? error.message : '删除测试计划失败')
    }
  }
}

async function removeTestCase(caseItem: ImportedTestCase) {
  try {
    await ElMessageBox.confirm(
      `确认删除用例「${caseItem.case_name}」？`,
      '删除AutoGLM',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
    await deleteImportedTestCase(caseItem.id)
    if (selectedPlan.value) {
      selectedPlan.value = await fetchTestPlan(selectedPlan.value.id)
    }
    await loadTestPlans()
    ElMessage.success('AutoGLM已删除')
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error(error instanceof Error ? error.message : '删除AutoGLM失败')
    }
  }
}

async function selectTestPlan(planId: number) {
  testPlanLoading.value = true
  try {
    selectedPlan.value = await fetchTestPlan(planId)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '测试计划加载失败')
  } finally {
    testPlanLoading.value = false
  }
}

// ── Folder (document) methods ──────────────────────────────────────────────────

async function handleCreateFolder() {
  if (!selectedPlan.value || !newFolderName.value.trim()) return
  try {
    await createTestCaseFolder(selectedPlan.value.id, {
      name: newFolderName.value.trim(),
      requirement_summary: newFolderSummary.value.trim() || undefined,
    })
    ElMessage.success('创建文档成功')
    showCreateFolderDialog.value = false
    newFolderName.value = ''
    newFolderSummary.value = ''
    selectedPlan.value = await fetchTestPlan(selectedPlan.value.id)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '创建文档失败')
  }
}

async function handleDeleteFolder(folder: TestCaseFolder) {
  try {
    await ElMessageBox.confirm(
      `确定要删除文档"${folder.name}"及其下所有用例吗？`,
      '确认删除',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
    await deleteTestCaseFolder(folder.id)
    ElMessage.success('删除成功')
    if (selectedFolderId.value === folder.id) {
      selectedFolderId.value = null
    }
    if (selectedPlan.value) {
      selectedPlan.value = await fetchTestPlan(selectedPlan.value.id)
    }
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error(error instanceof Error ? error.message : '删除失败')
    }
  }
}

function selectFolder(folderId: number | null) {
  selectedFolderId.value = folderId
}

async function handleBatchMove() {
  if (!moveTargetFolderId.value || selectedCaseRows.value.length === 0) return
  try {
    await batchMoveCasesToFolder(selectedCaseRows.value.map(c => c.id), moveTargetFolderId.value)
    ElMessage.success('移动成功')
    showMoveDialog.value = false
    if (selectedPlan.value) {
      selectedPlan.value = await fetchTestPlan(selectedPlan.value.id)
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '移动用例失败')
  }
}

const filteredTestCases = computed(() => {
  if (!selectedPlan.value) return []
  const cases = selectedPlan.value.cases
  if (selectedFolderId.value === null) return cases
  return cases.filter(c => c.folder_id === selectedFolderId.value)
})

function handleExcelFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  selectedExcelFile.value = input.files?.[0] ?? null
  if (selectedExcelFile.value && !projectName.value.trim()) {
    projectName.value = selectedExcelFile.value.name.replace(/\.[^.]+$/, '')
  }
}

async function importSelectedTestPlan() {
  if (!selectedExcelFile.value) {
    ElMessage.warning('请选择 Excel 或 CSV AutoGLM文件')
    return
  }
  importBusy.value = true
  try {
    const plan = await importTestPlan(
      selectedExcelFile.value,
      projectName.value.trim() || selectedExcelFile.value.name.replace(/\.[^.]+$/, ''),
    )
    selectedPlan.value = plan
    ElMessage.success(`已导入 ${plan.total_cases} 条用例`)
    await loadTestPlans()
    await selectTestPlan(plan.id)
    selectedExcelFile.value = null
    projectName.value = ''
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '导入失败')
  } finally {
    importBusy.value = false
  }
}

function handleRequirementFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  aiGenRequirementFile.value = input.files?.[0] ?? null
  if (aiGenRequirementFile.value && !aiGenProjectName.value.trim()) {
    aiGenProjectName.value = aiGenRequirementFile.value.name.replace(/\.[^.]+$/, '')
  }
}

async function generateFromRequirementDoc() {
  if (!aiGenRequirementFile.value) {
    ElMessage.warning('请选择需求文档')
    return
  }
  aiGenBusy.value = true
  aiGenPhase.value = 'extracting'
  aiGenErrorMessage.value = ''

  // Simulate phase transitions since backend is one request
  let phaseTimer: ReturnType<typeof setInterval> | null = setInterval(() => {
    if (aiGenPhase.value === 'extracting') aiGenPhase.value = 'generating'
    else if (aiGenPhase.value === 'generating') aiGenPhase.value = 'refining'
    else if (aiGenPhase.value === 'refining') aiGenPhase.value = 'saving'
  }, 30000)

  try {
    const result = await generateFromRequirement(
      aiGenRequirementFile.value,
      aiGenProjectName.value.trim() || aiGenRequirementFile.value.name.replace(/\.[^.]+$/, ''),
      aiGenTargetApp.value,
    )
    if (phaseTimer) clearInterval(phaseTimer)
    aiGenPhase.value = 'done'

    selectedPlan.value = await fetchTestPlan(result.id)
    await loadTestPlans()
    await selectTestPlan(result.id)

    ElMessage.success(`AI 已生成 ${result.total_cases} 条测试用例`)

    // Reset state
    aiGenRequirementFile.value = null
    aiGenProjectName.value = ''
    aiGenPhase.value = 'idle'
  } catch (error) {
    if (phaseTimer) clearInterval(phaseTimer)
    aiGenPhase.value = 'idle'
    aiGenErrorMessage.value = error instanceof Error ? error.message : 'AI生成失败'
    ElMessage.error(aiGenErrorMessage.value)
  } finally {
    aiGenBusy.value = false
  }
}

function openManualCaseDialog() {
  manualCaseForm.value = {
    case_name: '',
    folder_id: null,
    system_name: '',
    module: '',
    precondition: '',
    stepsText: '',
    expected_result: '',
    priority: '',
    target_app: '乐有家测试版',
    test_module: '',
  }
  manualCaseRunAfterSave.value = true
  manualCaseDialogVisible.value = true
}

async function submitManualCase() {
  if (!selectedPlan.value) return
  const form = manualCaseForm.value
  const steps = parseManualSteps(form.stepsText)
  if (!form.case_name.trim()) {
    ElMessage.warning('请填写用例名称')
    return
  }
  if (!form.precondition.trim()) {
    ElMessage.warning('请填写前置条件')
    return
  }
  if (steps.length === 0) {
    ElMessage.warning('请至少填写一个用例步骤')
    return
  }
  if (!form.expected_result.trim()) {
    ElMessage.warning('请填写预期结果')
    return
  }
  const shouldRunAfterSave = manualCaseRunAfterSave.value && activeRunnableDevice.value
  manualCaseBusy.value = true
  try {
    const created = await createImportedTestCase(selectedPlan.value.id, {
      case_name: form.case_name.trim(),
      folder_id: form.folder_id,
      system_name: form.system_name.trim() || null,
      module: form.module.trim() || null,
      precondition: form.precondition.trim() || null,
      steps,
      expected_result: form.expected_result.trim(),
      priority: form.priority.trim() || null,
      target_app: form.target_app,
      test_module: form.test_module.trim() || null,
    })
    manualCaseDialogVisible.value = false
    selectedPlan.value = await fetchTestPlan(selectedPlan.value.id)
    await loadTestPlans()
    if (shouldRunAfterSave) {
      const result = await executeCaseWithStream(created.id)
      ElMessage.info(result?.result_note || '用例已创建并执行完成')
      if (selectedPlan.value) selectedPlan.value = await fetchTestPlan(selectedPlan.value.id)
    } else {
      ElMessage.success('已新增单条AutoGLM')
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '新增用例失败')
  } finally {
    manualCaseBusy.value = false
  }
}

function expandCase(caseId: number) {
  if (!expandedCaseIds.value.includes(caseId)) {
    expandedCaseIds.value = [...expandedCaseIds.value, caseId]
  }
}

function collapseCase(caseId: number) {
  expandedCaseIds.value = expandedCaseIds.value.filter(id => id !== caseId)
  if (expandedCaseId.value === caseId) {
    expandedCaseId.value = null
    expandedExecutionDetail.value = null
  }
}

async function executeCaseWithStream(caseId: number) {
  const clientRunId = createClientRunId(`case-${caseId}`)
  const controller = new AbortController()
  caseRunIds.set(caseId, clientRunId)
  caseControllers.set(caseId, controller)
  startCaseLog(caseId)
  expandCase(caseId)
  expandedExecutionDetail.value = null
  try {
    return await runImportedTestCaseStream(
      caseId,
      {
        device_udid: activeDeviceUdid.value || null,
        device_platform: activeDevicePlatform.value || null,
        client_run_id: clientRunId,
      },
      event => appendCaseLog(caseId, event),
      controller.signal,
    )
  } finally {
    caseControllers.delete(caseId)
    caseRunIds.delete(caseId)
    finishCaseLog(caseId)
  }
}

async function runCase(caseItem: ImportedTestCase) {
  if (!requireRunnableDevice()) return
  try {
    const result = await executeCaseWithStream(caseItem.id)
    ElMessage.info(result?.result_note || '执行完成')
    if (selectedPlan.value) {
      selectedPlan.value = await fetchTestPlan(selectedPlan.value.id)
    }
  } catch (error) {
    if (isAbortError(error)) {
      ElMessage.warning('已停止执行')
    } else {
      ElMessage.error(error instanceof Error ? error.message : '执行失败')
    }
  }
}

async function stopCaseRun(caseId: number) {
  const runId = caseRunIds.get(caseId)
  appendCaseLog(caseId, {
    event: 'log',
    phase: 'execution',
    message: '正在停止当前用例...',
    timestamp: new Date().toISOString(),
  })
  if (runId) {
    try {
      await cancelTestRun(runId)
    } catch (error) {
      console.warn('Failed to cancel case run:', error)
    }
  }
  caseControllers.get(caseId)?.abort()
  finishCaseLog(caseId)
}

function resolveCaseRunId(caseId: number) {
  return caseRunIds.get(caseId) || batchRunId.value
}

async function resumeCaseRun(caseId: number) {
  const runId = resolveCaseRunId(caseId)
  if (!runId) {
    ElMessage.warning('当前没有可继续的执行进程')
    return
  }
  resumingCaseIds.value = { ...resumingCaseIds.value, [caseId]: true }
  try {
    await resumeTestRun(runId)
    appendCaseLog(caseId, {
      event: 'log',
      phase: 'execution',
      message: '已发送继续执行信号，等待 AutoGLM 继续运行...',
      timestamp: new Date().toISOString(),
    })
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '继续执行失败')
  } finally {
    resumingCaseIds.value = { ...resumingCaseIds.value, [caseId]: false }
  }
}

async function runPlan() {
  if (!selectedPlan.value) return
  if (!requireRunnableDevice()) return
  const clientRunId = createClientRunId(`plan-${selectedPlan.value.id}`)
  const controller = new AbortController()
  batchRunId.value = clientRunId
  batchController.value = controller
  batchRunning.value = true
  batchProgress.value = {
    totalCases: selectedPlan.value.total_cases,
    completedCases: 0,
    currentCaseId: null,
    currentCaseName: '',
  }
  try {
    const result = await runImportedTestPlanStream(
      selectedPlan.value.id,
      {
        device_udid: activeDeviceUdid.value || null,
        device_platform: activeDevicePlatform.value || null,
        client_run_id: clientRunId,
      },
      event => {
        if (event.event === 'batch_start') {
          batchProgress.value.totalCases = event.total_cases ?? batchProgress.value.totalCases
          return
        }
        if (!event.case_id) {
          if (event.event === 'batch_result') {
            finishAllCaseLogs()
          }
          return
        }
        if (event.event === 'case_start') {
          startCaseLog(event.case_id)
          expandCase(event.case_id)
          batchProgress.value.currentCaseId = event.case_id
          batchProgress.value.currentCaseName = event.case_name || event.message || ''
          return
        }
        appendCaseLog(event.case_id, event)
        if (event.event === 'result') {
          finishCaseLog(event.case_id)
          batchProgress.value.completedCases += 1
        } else if (event.event === 'need_user') {
          batchProgress.value.currentCaseId = event.case_id
          batchProgress.value.currentCaseName = event.case_name || batchProgress.value.currentCaseName
        }
      },
      controller.signal,
    )
    ElMessage.info(result?.message || '批量执行完成')
    selectedPlan.value = await fetchTestPlan(selectedPlan.value.id)
  } catch (error) {
    if (isAbortError(error)) {
      ElMessage.warning('已停止批量执行')
    } else {
      ElMessage.error(error instanceof Error ? error.message : '批量执行失败')
    }
  } finally {
    finishAllCaseLogs()
    batchRunning.value = false
    batchRunId.value = null
    batchController.value = null
    batchProgress.value.currentCaseId = null
    batchProgress.value.currentCaseName = ''
  }
}

async function stopPlanRun() {
  const runId = batchRunId.value
  if (runId) {
    try {
      await cancelTestRun(runId)
    } catch (error) {
      console.warn('Failed to cancel batch run:', error)
    }
  }
  batchController.value?.abort()
  finishAllCaseLogs()
  batchRunning.value = false
}

function createClientRunId(prefix: string) {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

function isAbortError(error: unknown) {
  return error instanceof DOMException && error.name === 'AbortError'
}

// User input polling
async function pollUserInputRequests() {
  try {
    const requests = await fetchPendingInputRequests()
    if (requests.length > 0 && !userInputDialogVisible.value) {
      currentInputRequest.value = requests[0]
      userInputValue.value = ''
      userInputDialogVisible.value = true
    }
  } catch {
    // Ignore polling errors
  }
}

async function submitUserInput() {
  if (!currentInputRequest.value) return
  try {
    await respondToInputRequest(currentInputRequest.value.id, userInputValue.value)
    userInputDialogVisible.value = false
    currentInputRequest.value = null
    userInputValue.value = ''
  } catch (error) {
    ElMessage.error('提交失败')
  }
}

async function cancelUserInput() {
  if (!currentInputRequest.value) return
  try {
    await cancelInputRequest(currentInputRequest.value.id)
    userInputDialogVisible.value = false
    currentInputRequest.value = null
    userInputValue.value = ''
  } catch {
    // Ignore cancel errors
  }
}

// Test report
async function openTestReport() {
  if (!selectedPlan.value) return
  reportLoading.value = true
  try {
    testPlanReport.value = await fetchTestPlanReport(selectedPlan.value.id)
    planReportDialogVisible.value = true
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '加载报告失败')
  } finally {
    reportLoading.value = false
  }
}

async function exportReport(format: 'json' | 'html') {
  if (!selectedPlan.value) return
  try {
    const result = await exportTestPlanReport(selectedPlan.value.id, format)
    if (format === 'html' && result.html) {
      const blob = new Blob([result.html], { type: 'text/html' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = result.filename
      a.click()
      URL.revokeObjectURL(url)
      ElMessage.success('报告已导出')
    } else {
      const blob = new Blob([JSON.stringify(result.report || result, null, 2)], {
        type: 'application/json;charset=utf-8',
      })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = result.filename || `test_report_${selectedPlan.value.id}.json`
      a.click()
      URL.revokeObjectURL(url)
      ElMessage.success('报告已导出')
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '导出失败')
  }
}

function viewExecutionDetail(executionId: number) {
  selectedExecutionId.value = executionId
  executionReportDialogVisible.value = true
}

async function toggleCaseExpand(row: ImportedTestCase) {
  if (expandedCaseIds.value.includes(row.id)) {
    collapseCase(row.id)
    return
  }

  expandCase(row.id)
  expandedCaseId.value = row.id
  expandedExecutionDetail.value = null

  if (!row.latest_result || row.latest_result === 'pending') {
    return
  }

  // Load testPlanReport if not already loaded to get execution_id
  if (!testPlanReport.value && selectedPlan.value) {
    try {
      testPlanReport.value = await fetchTestPlanReport(selectedPlan.value.id)
    } catch (error) {
      console.error('Failed to load test plan report:', error)
      return
    }
  }

  const executionId = getExecutionIdFromReport(row.id)
  if (!executionId) {
    return
  }

  await loadCaseExecutionDetail(row.id, executionId)
}

async function loadCaseExecutionDetail(caseId: number, executionId: number) {
  expandedLoading.value = true
  try {
    expandedExecutionDetail.value = await fetchExecutionDetailReport(executionId)
  } catch (error) {
    console.error('Failed to load execution detail:', error)
  } finally {
    expandedLoading.value = false
  }
}

// Auto-refresh
const { start: startDevicePolling, stop: stopDevicePolling } = usePolling(
  async () => {
    await deviceStore.loadDevices(false)
    autoConnectActiveDevice()
  },
  { interval: 3000 },
)

onMounted(() => {
  deviceStore.loadDevices(true).then(autoConnectActiveDevice)
  loadTestPlans()
  loadLoginAccounts()
  startDevicePolling()
  inputPollTimer.value = window.setInterval(pollUserInputRequests, 1000)
})

onBeforeUnmount(() => {
  stopDevicePolling()
  if (inputPollTimer.value !== null) {
    window.clearInterval(inputPollTimer.value)
  }
  if (batchRunId.value) {
    cancelTestRun(batchRunId.value).catch(() => undefined)
  }
  batchController.value?.abort()
  caseRunIds.forEach(runId => {
    cancelTestRun(runId).catch(() => undefined)
  })
  caseControllers.forEach(controller => controller.abort())
  // Disconnect on route change — the next page will re-connect with
  // its own options (e.g. control:true vs control:false).
  screen.disconnect()
})

watch(
  () => [
    deviceStore.activeDevice?.udid,
    deviceStore.activeDevice?.status,
    deviceStore.activeDevice?.platform,
  ],
  () => autoConnectActiveDevice(),
  { flush: 'post' },
)
</script>

<template>
  <div class="page-shell">
    <!-- Top Bar -->
    <header class="topbar">
      <div class="topbar-left">
        <h1 class="page-title">AutoGLM管理</h1>
        <div class="device-info">
          <span class="label">当前设备</span>
          <span v-if="deviceStore.activeDevice" class="value">
            {{ deviceStore.activeDevice.model || deviceStore.activeDevice.product || deviceStore.activeDevice.udid }}
            <el-tag :type="statusType(deviceStore.activeDevice.status)" effect="light" size="small">{{ deviceStore.activeDevice.status }}</el-tag>
          </span>
          <span v-else class="value empty">未选择设备</span>
        </div>
      </div>
      <div class="topbar-actions">
        
        <el-button :icon="User" size="small" @click="openLoginAccountDialog()">
          账号密码配置
        </el-button>
        <el-dropdown v-if="deviceStore.devices.length > 0" trigger="click" @command="selectDevice">
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
        <el-button :icon="Refresh" :loading="deviceStore.loading" size="small" @click="refreshDevices">刷新设备</el-button>
      </div>
    </header>

    <!-- Main Content -->
    <div class="main-content">
      <!-- Left Sidebar -->
      <div class="left-sidebar">
        <div class="sidebar-section">
          <div class="sidebar-header">
            <span>导入测试计划</span>
          </div>
          <div class="import-box">
            <label class="field-label">项目名称</label>
            <el-input v-model="projectName" size="small" placeholder="从 Excel/CSV 导入测试计划" />
            <label class="file-picker">
              <el-icon><UploadFilled /></el-icon>
              <span>{{ selectedExcelFile?.name || '选择 Excel/CSV 文件' }}</span>
              <input accept=".xlsx,.xlsm,.csv" type="file" @change="handleExcelFileChange" />
            </label>
            <el-button
              :loading="importBusy"
              :disabled="!selectedExcelFile"
              size="small"
              type="primary"
              @click="importSelectedTestPlan"
            >
              导入用例
            </el-button>
          </div>
        </div>

        <div class="sidebar-section">
          <div class="sidebar-header">
            <span>AI生成用例</span>
          </div>
          <div class="ai-gen-box">
            <label class="field-label">项目名称</label>
            <el-input v-model="aiGenProjectName" size="small" placeholder="AI生成的测试计划名称" />
            <label class="field-label">目标应用</label>
            <el-select v-model="aiGenTargetApp" size="small" placeholder="选择目标应用">
              <el-option label="乐有家测试版" value="乐有家测试版" />
              <el-option label="乐办公测试版" value="乐办公测试版" />
              <el-option label="微信小程序" value="微信小程序" />
            </el-select>
            <label class="file-picker">
              <el-icon><MagicStick /></el-icon>
              <span>{{ aiGenRequirementFile?.name || '选择需求文档 (PDF/Word/TXT/Excel)' }}</span>
              <input accept=".txt,.pdf,.docx,.doc,.xlsx,.xlsm,.csv" type="file" @change="handleRequirementFileChange" />
            </label>
            <div v-if="aiGenBusy" class="ai-gen-progress">
              <el-steps :active="aiGenPhaseStepIndex" finish-status="process" simple>
                <el-step title="提取" />
                <el-step title="生成" />
                <el-step title="优化" />
                <el-step title="保存" />
              </el-steps>
            </div>
            <div v-if="aiGenErrorMessage" class="ai-gen-error">
              <el-alert :closable="true" type="error" :title="aiGenErrorMessage" @close="aiGenErrorMessage = ''" />
            </div>
            <el-button
              :loading="aiGenBusy"
              :disabled="!aiGenRequirementFile"
              size="small"
              type="warning"
              @click="generateFromRequirementDoc"
            >
              {{ aiGenBusy ? `正在${aiGenPhaseLabel}...` : 'AI生成用例' }}
            </el-button>
          </div>
        </div>

        <div class="sidebar-section">
          <div class="sidebar-header">
            <span>测试计划</span>
            <el-button :icon="Refresh" :loading="testPlanLoading" size="small" text @click="loadTestPlans" />
          </div>
          <div class="plan-list" v-loading="testPlanLoading">
            <button
              v-for="plan in testPlans"
              :key="plan.id"
              class="plan-item"
              :class="{ active: selectedPlan?.id === plan.id }"
              type="button"
              @click="selectTestPlan(plan.id)"
            >
              <el-icon><Document /></el-icon>
              <div class="plan-info">
                <span class="plan-name">{{ plan.name }}</span>
                <span class="plan-meta">{{ plan.total_cases }} cases · {{ plan.imported_at.slice(0, 10) }}</span>
              </div>
              <el-icon class="plan-delete" @click.stop="removeTestPlan(plan)"><Delete /></el-icon>
            </button>
            <div v-if="testPlans.length === 0" class="empty-sidebar">
              <span>暂无测试计划</span>
            </div>
          </div>
        </div>
      </div>

      <!-- Right Content -->
      <div class="right-content">
        <div v-if="!selectedPlan" class="empty-state">
          <el-icon :size="48"><UploadFilled /></el-icon>
          <h2>导入测试计划</h2>
          <p>在左侧选择 Excel/CSV 文件导入AutoGLM，或选择一个已有计划查看详情</p>
        </div>

        <div v-else class="plan-detail">
          <div class="detail-header">
            <div>
              <p class="eyebrow">Project Test Plan</p>
              <h2>{{ selectedPlan.name }}</h2>
              <p class="plan-summary">
                {{ selectedPlan.total_cases }} 条用例 · 来源：{{ selectedPlan.source_filename || '-' }} · 导入于 {{ selectedPlan.imported_at.slice(0, 10) }}
              </p>
            </div>
            <div class="detail-actions">
              <el-tag size="small" :type="activeRunnableDevice ? 'success' : 'info'">
                {{ activeRunnableDevice ? `设备 ${activeRunnableDevice.model || activeRunnableDevice.udid}` : '未选择在线设备' }}
              </el-tag>
              <el-button
                :icon="DataAnalysis"
                :loading="reportLoading"
                size="small"
                @click="openTestReport"
              >
                查看报告
              </el-button>
              <el-button
                :icon="Plus"
                size="small"
                @click="openManualCaseDialog"
              >
                新增用例
              </el-button>
              <el-button
                v-if="selectedCaseRows.length > 0"
                size="small"
                type="warning"
                plain
                @click="openBatchEditDialog"
              >
                批量编辑 ({{ selectedCaseRows.length }})
              </el-button>
              <el-button
                v-if="selectedCaseRows.length > 0"
                size="small"
                plain
                @click="showMoveDialog = true; moveTargetFolderId = null"
              >
                移动到文档 ({{ selectedCaseRows.length }})
              </el-button>
              <el-button
                :icon="batchRunning ? Close : VideoPlay"
                :disabled="!selectedPlan || (!activeRunnableDevice && !batchRunning)"
                size="small"
                :type="batchRunning ? 'danger' : 'primary'"
                @click="batchRunning ? stopPlanRun() : runPlan()"
              >
                {{ batchRunning ? '停止批量' : '批量执行' }}
              </el-button>
              <el-tag
                v-if="batchRunning"
                size="small"
                type="warning"
                effect="light"
              >
                {{ batchProgress.completedCases }}/{{ batchProgress.totalCases || selectedPlan.total_cases }} ·
                {{ batchProgress.currentCaseName || '批量执行中' }}
              </el-tag>
              <el-tooltip v-if="!activeRunnableDevice" content="请先连接在线设备" placement="top">
                <el-tag size="small" type="info">无设备</el-tag>
              </el-tooltip>
            </div>
          </div>

          <div class="account-config-strip">
            <div class="account-strip-info">
              <span>账号密码配置</span>
              <strong>{{ loginAccounts.length }}</strong>
              <span>条</span>
            </div>
            <div class="account-strip-actions">
              <el-button size="small" text type="primary" @click="openLoginAccountDialog()">新增</el-button>
              <el-button size="small" text @click="loadLoginAccounts">刷新</el-button>
            </div>
          </div>

          <!-- 文档列表 -->
          <div class="folder-section">
            <div class="folder-header">
              <span class="folder-title">测试用例文档</span>
              <el-button size="small" type="primary" @click="showCreateFolderDialog = true; newFolderName = ''; newFolderSummary = ''">
                <el-icon><Plus /></el-icon> 新建文档
              </el-button>
            </div>
            <div class="folder-list">
              <div
                class="folder-card"
                :class="{ active: selectedFolderId === null }"
                @click="selectFolder(null)"
              >
                <span class="folder-card-name">全部</span>
                <span class="folder-card-count">{{ selectedPlan.cases.length }}条</span>
              </div>
              <div
                v-for="folder in selectedPlan.folders || []"
                :key="folder.id"
                class="folder-card"
                :class="{ active: selectedFolderId === folder.id }"
                @click="selectFolder(folder.id)"
              >
                <span class="folder-card-name">{{ folder.name }}</span>
                <span class="folder-card-count">{{ folder.total_cases }}条</span>
                <el-tag v-if="folder.source_type === 'ai_generated'" size="small" type="success">AI</el-tag>
                <el-tag v-if="folder.source_type === 'import_grouped'" size="small" type="info">导入</el-tag>
                <el-icon class="folder-card-more" @click.stop="handleDeleteFolder(folder)"><Delete /></el-icon>
              </div>
            </div>
          </div>

          <el-table
            v-loading="testPlanLoading"
            :data="filteredTestCases"
            class="case-table"
            stripe
            height="100%"
            row-key="id"
            :expand-row-keys="expandedCaseIds"
            @row-click="toggleCaseExpand"
            @selection-change="handleCaseSelectionChange"
          >
            <el-table-column type="selection" width="45" />
            <el-table-column type="expand" width="50">
              <template #default="{ row }">
                <!-- Real-time execution logs -->
                <div v-if="getCaseLogs(row.id).length > 0" class="run-log-panel">
                  <div class="run-log-header">
                    <span>AutoGLM 实时日志</span>
                    <el-tag
                      v-if="runningCaseId === row.id"
                      size="small"
                      type="warning"
                      effect="light"
                    >
                      执行中
                    </el-tag>
                  </div>
                  <CaseStepLog
                    :events="getCaseLogs(row.id)"
                    @preview="(url: string) => { /* handled by expand detail */ }"
                  />
                  <div
                    v-if="isCaseWaitingForUser(row.id)"
                    class="resume-row"
                  >
                    <el-button
                      size="small"
                      type="warning"
                      :loading="Boolean(resumingCaseIds[row.id])"
                      @click.stop="resumeCaseRun(row.id)"
                    >
                      继续执行
                    </el-button>
                  </div>
                </div>

                <!-- Loading historical detail -->
                <div v-else-if="expandedLoading && expandedCaseId === row.id" class="expand-loading">
                  <el-icon class="is-loading"><Loading /></el-icon>
                  <span>加载执行详情...</span>
                </div>

                <!-- Historical execution detail -->
                <div v-else-if="expandedExecutionDetail && expandedCaseId === row.id" class="expand-content">
                  <div class="expand-header">
                    <span class="expand-device">设备: {{ expandedExecutionDetail.device_udid || '未知' }}</span>
                    <span class="expand-duration">耗时: {{ expandedExecutionDetail.duration_ms ? `${(expandedExecutionDetail.duration_ms / 1000).toFixed(1)}s` : '-' }}</span>
                    <span v-if="expandedExecutionDetail.trace_id" class="expand-trace">
                      Trace: <code>{{ expandedExecutionDetail.trace_id.slice(0, 12) }}...</code>
                    </span>
                  </div>
                  <CaseStepLog
                    :events="expandedExecutionEvents"
                    @preview="(url: string) => { /* screenshot preview */ }"
                  />
                </div>

                <!-- Empty state -->
                <div v-else class="expand-empty">
                  <span>暂无执行详情</span>
                </div>
              </template>
            </el-table-column>
            <el-table-column prop="sequence" label="序号" width="68" fixed />
            <el-table-column prop="case_name" label="用例名称" min-width="180" show-overflow-tooltip />
            <el-table-column label="所属文档" width="140">
              <template #default="{ row }">
                <el-tag size="small" v-if="row.folder_name">{{ row.folder_name }}</el-tag>
                <span v-else class="text-muted">未分类</span>
              </template>
            </el-table-column>
            <el-table-column prop="system_name" label="所属系统" width="100" show-overflow-tooltip />
            <el-table-column prop="module" label="所属模块" width="100" show-overflow-tooltip />
            <el-table-column prop="target_app" label="目标应用" width="120" show-overflow-tooltip />
            <el-table-column prop="test_module" label="测试模块" width="120" show-overflow-tooltip />
            <el-table-column prop="precondition" label="*前置条件" min-width="160" show-overflow-tooltip>
              <template #default="{ row }">
                <span v-if="row.precondition" class="precondition-text">{{ row.precondition }}</span>
                <span v-else class="text-muted">—</span>
              </template>
            </el-table-column>
            <el-table-column label="*用例步骤" min-width="220">
              <template #default="{ row }">
                <pre class="case-steps">{{ formatCaseSteps(row.steps) }}</pre>
              </template>
            </el-table-column>
            <el-table-column prop="expected_result" label="*预期结果" min-width="140" show-overflow-tooltip />
            <el-table-column prop="priority" label="优先级" width="70" />
            <el-table-column prop="run_count" label="执行次数" width="85" />
            <el-table-column label="最新结果" width="90">
              <template #default="{ row }">
                <el-tag :type="resultType(row.latest_result)" effect="light" size="small">
                  {{ row.latest_result || '未执行' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="latest_result_note" label="结果说明" min-width="180" show-overflow-tooltip />
            <el-table-column label="操作" width="170" fixed="right">
              <template #default="{ row }">
                <el-tooltip v-if="!activeRunnableDevice" content="请先连接在线设备" placement="top">
                  <span>
                    <el-button
                      :icon="VideoPlay"
                      :loading="isCaseRunning(row.id)"
                      :disabled="true"
                      size="small"
                      type="primary"
                      @click.stop
                    >
                      执行
                    </el-button>
                  </span>
                </el-tooltip>
                <el-button
                  v-else
                  :icon="isCaseRunning(row.id) ? Close : VideoPlay"
                  :disabled="hasRunningCase && !isCaseRunning(row.id)"
                  size="small"
                  :type="isCaseRunning(row.id) ? 'danger' : 'primary'"
                  @click.stop="isCaseRunning(row.id) ? stopCaseRun(row.id) : runCase(row)"
                >
                  {{ isCaseRunning(row.id) ? '停止' : '执行' }}
                </el-button>
                <el-button
                  :icon="Delete"
                  size="small"
                  type="danger"
                  plain
                  @click.stop="removeTestCase(row)"
                />
              </template>
            </el-table-column>
          </el-table>
        </div>
      </div>

      <aside class="phone-panel">
        <div class="phone-header">
          <div>
            <strong>实时手机画面</strong>
            <span>{{ deviceStore.activeDevice?.udid || '未选择设备' }}</span>
          </div>
          <el-tag size="small" :type="screen.state.value.isConnected ? 'success' : 'info'">{{ screen.state.value.isConnected ? '已连接' : '未连接' }}</el-tag>
        </div>

        <div class="phone-screen"
          @pointerdown="handlePhonePointerDown"
          @pointermove="handlePhonePointerMove"
          @pointerup="handlePhonePointerUp"
          @pointercancel="handlePhonePointerCancel"
          @keydown="handlePhoneKeyDown"
          tabindex="0"
        >
          <div v-if="screen.state.value.mode === 'scrcpy-native' && deviceStore.activeDevice" :ref="screen.setNativeHost" class="phone-native-host">
            <div v-if="screen.state.value.isLoading" class="phone-state native">
              <el-icon class="is-loading" :size="28"><Loading /></el-icon>
              <span>启动原生投屏...</span>
            </div>
            <div v-else-if="screen.state.value.error" class="phone-state error native">
              <span>{{ screen.state.value.error }}</span>
            </div>
          </div>
          <div v-else-if="screen.state.value.isLoading" class="phone-state">
            <el-icon class="is-loading" :size="28"><Loading /></el-icon>
            <span>连接投屏中...</span>
          </div>
          <div v-else-if="screen.state.value.error" class="phone-state error">
            <span>{{ screen.state.value.error }}</span>
          </div>
          <div v-else-if="!deviceStore.activeDevice" class="phone-state">
            <el-icon :size="32"><Cellphone /></el-icon>
            <span>选择或连接移动设备</span>
          </div>
          <video
            v-else-if="isEmbeddedVideoStream"
            :ref="screen.setVideo"
            class="phone-video"
            :style="{ aspectRatio: screenAspectRatio }"
            muted
            autoplay
            playsinline
          />
          <div
            v-else-if="isScrcpyWebCodecsStream"
            :ref="screen.setYumeHost"
            class="phone-yume-host"
          />
          <canvas v-else :ref="screen.setCanvas" class="phone-canvas" />
        </div>

        <div class="phone-meta">
          <div class="phone-nav" v-if="deviceStore.activeDevice">
            <button class="phone-nav-btn" title="返回" :disabled="!screen.state.value.isConnected" @click="sendPhoneNavKey('BACK')">◀</button>
            <button class="phone-nav-btn" title="桌面" :disabled="!screen.state.value.isConnected" @click="sendPhoneNavKey('HOME')">●</button>
            <button class="phone-nav-btn" title="任务窗" :disabled="!screen.state.value.isConnected" @click="sendPhoneNavKey('APP_SWITCH')">■</button>
          </div>
          <span>Provider: {{ screen.state.value.provider || '-' }}</span>
          <span>{{ screen.state.value.fps }} fps</span>
        </div>
        <el-alert v-if="screen.state.value.notice" class="phone-notice" :title="screen.state.value.notice" type="warning" show-icon />
      </aside>
    </div>

    <!-- Dialogs -->
    <el-dialog v-model="manualCaseDialogVisible" title="新增单条AutoGLM" width="560px" destroy-on-close>
      <div class="manual-case-form">
        <label class="field-label">用例名称</label>
        <el-input v-model="manualCaseForm.case_name" placeholder="例如：验证搜索按钮跳转结果页" />
        <div class="manual-case-grid">
          <div>
            <label class="field-label">所属文档</label>
            <el-select v-model="manualCaseForm.folder_id" placeholder="选择文档" clearable style="width: 100%">
              <el-option
                v-for="folder in selectedPlan?.folders || []"
                :key="folder.id"
                :label="folder.name"
                :value="folder.id"
              />
            </el-select>
          </div>
          <div>
            <label class="field-label">所属系统</label>
            <el-select v-model="manualCaseForm.system_name" placeholder="选择或输入" clearable filterable allow-create>
              <el-option v-for="s in systemNamePresets" :key="s" :label="s" :value="s" />
            </el-select>
          </div>
          <div>
            <label class="field-label">所属模块</label>
            <el-select v-model="manualCaseForm.module" placeholder="选择或输入" clearable filterable allow-create>
              <el-option v-for="m in modulePresets" :key="m" :label="m" :value="m" />
            </el-select>
          </div>
        </div>
        <div class="manual-case-grid">
          <div>
            <label class="field-label">目标应用</label>
            <el-select v-model="manualCaseForm.target_app" placeholder="选择目标应用">
              <el-option label="乐有家测试版" value="乐有家测试版" />
              <el-option label="乐办公测试版" value="乐办公测试版" />
              <el-option label="微信小程序" value="微信小程序" />
            </el-select>
          </div>
          <div>
            <label class="field-label">测试模块</label>
            <el-select v-model="manualCaseForm.test_module" placeholder="选择测试模块" clearable filterable allow-create>
              <el-option v-for="m in testModulePresets" :key="m" :label="m" :value="m" />
            </el-select>
          </div>
        </div>
        <div class="manual-case-grid">
          <div>
            <label class="field-label">优先级</label>
            <el-select v-model="manualCaseForm.priority" clearable placeholder="可选">
              <el-option label="高" value="高" />
              <el-option label="中" value="中" />
              <el-option label="低" value="低" />
            </el-select>
          </div>
        </div>
        <label class="field-label"><span class="required-mark">*</span>前置条件</label>
        <el-input v-model="manualCaseForm.precondition" placeholder="例如：用户已进入小程序首页" />
        <label class="field-label"><span class="required-mark">*</span>用例步骤</label>
        <el-input v-model="manualCaseForm.stepsText" type="textarea" :rows="6" placeholder="每行一个步骤，必填" />
        <label class="field-label"><span class="required-mark">*</span>预期结果</label>
        <el-input v-model="manualCaseForm.expected_result" type="textarea" :rows="3" placeholder="例如：页面展示对应搜索结果" />
        <el-checkbox v-model="manualCaseRunAfterSave" :disabled="!activeRunnableDevice">
          保存后立即执行
        </el-checkbox>
        <el-tag v-if="!activeRunnableDevice" size="small" type="info" effect="light">需要连接在线设备才能执行</el-tag>
      </div>
      <template #footer>
        <el-button :disabled="manualCaseBusy" @click="manualCaseDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="manualCaseBusy" @click="submitManualCase">
          {{ manualCaseRunAfterSave && activeRunnableDevice ? '保存并执行' : '保存' }}
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="batchEditDialogVisible" title="批量编辑用例" width="480px" destroy-on-close>
      <div class="manual-case-form">
        <el-alert :closable="false" effect="light" type="info" style="margin-bottom: 16px">
          已选择 {{ selectedCaseRows.length }} 条用例。选择新值修改字段，勾选"清空"则将该字段置空，留空且不勾选则不修改。
        </el-alert>
        <div class="manual-case-grid">
          <div>
            <label class="field-label">所属系统</label>
            <div class="batch-field-row">
              <el-select v-model="batchEditForm.system_name" placeholder="不修改" clearable filterable allow-create :disabled="batchEditClear.system_name">
                <el-option v-for="s in batchEditSystemNamePresets" :key="s" :label="s" :value="s" />
              </el-select>
              <el-checkbox v-model="batchEditClear.system_name" label="清空" />
            </div>
          </div>
          <div>
            <label class="field-label">所属模块</label>
            <div class="batch-field-row">
              <el-select v-model="batchEditForm.module" placeholder="不修改" clearable filterable allow-create :disabled="batchEditClear.module">
                <el-option v-for="m in batchEditModulePresets" :key="m" :label="m" :value="m" />
              </el-select>
              <el-checkbox v-model="batchEditClear.module" label="清空" />
            </div>
          </div>
        </div>
        <div class="manual-case-grid">
          <div>
            <label class="field-label">目标应用</label>
            <div class="batch-field-row">
              <el-select v-model="batchEditForm.target_app" placeholder="不修改" clearable :disabled="batchEditClear.target_app">
                <el-option label="乐有家测试版" value="乐有家测试版" />
                <el-option label="乐办公测试版" value="乐办公测试版" />
                <el-option label="微信小程序" value="微信小程序" />
              </el-select>
              <el-checkbox v-model="batchEditClear.target_app" label="清空" />
            </div>
          </div>
          <div>
            <label class="field-label">测试模块</label>
            <div class="batch-field-row">
              <el-select v-model="batchEditForm.test_module" placeholder="不修改" clearable filterable allow-create :disabled="batchEditClear.test_module">
                <el-option v-for="m in batchEditTestModulePresets" :key="m" :label="m" :value="m" />
              </el-select>
              <el-checkbox v-model="batchEditClear.test_module" label="清空" />
            </div>
          </div>
        </div>
      </div>
      <template #footer>
        <el-button @click="batchEditDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="batchEditBusy" @click="submitBatchEdit">确认修改</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="loginAccountDialogVisible" :title="loginAccountForm.id ? '编辑账号密码配置' : '新增账号密码配置'" width="620px" destroy-on-close>
      <div class="login-account-layout">
        <div class="login-account-list">
          <div class="account-list-header">
            <span>已配置账号</span>
            <el-button size="small" text type="primary" @click="resetLoginAccountForm()">新建</el-button>
          </div>
          <div v-if="loginAccounts.length === 0" class="account-empty">暂无账号配置</div>
          <button v-for="account in loginAccounts" :key="account.id" class="account-row"
            :class="{ active: loginAccountForm.id === account.id }" type="button"
            @click="openLoginAccountDialog(account)">
            <span class="account-name">
              {{ account.platform }} · {{ account.label }}
              <el-tag v-if="account.use_for_autoglm" size="small" type="success" effect="plain" style="margin-left: 4px">AutoGLM</el-tag>
            </span>
            <span class="account-meta">{{ account.login_id }} / {{ account.password_masked }}</span>
          </button>
        </div>
        <div class="login-account-form">
          <label class="field-label">平台</label>
          <el-select v-model="loginAccountForm.platform" allow-create filterable default-first-option placeholder="选择或输入平台">
            <el-option v-for="platform in platformOptions" :key="platform" :label="platform" :value="platform" />
          </el-select>
          <label class="field-label">配置名称</label>
          <el-input v-model="loginAccountForm.label" placeholder="例如：常用微信、测试QQ、乐有家测试账号" />
          <label class="field-label">手机号 / 账号</label>
          <el-input v-model="loginAccountForm.login_id" placeholder="手机号、QQ号、微信号或乐有家账号" />
          <label class="field-label">密码</label>
          <el-input v-model="loginAccountForm.password" type="password" show-password autocomplete="off"
            :placeholder="loginAccountForm.id ? '留空保留当前密码' : '请输入密码'" />
          <label class="field-label">备注</label>
          <el-input v-model="loginAccountForm.note" placeholder="可选，例如：仅测试环境使用" />
          <label class="field-label">
            <el-switch v-model="loginAccountForm.use_for_autoglm" size="small" />
            <span style="margin-left:8px">AutoGLM 自动登录使用</span>
          </label>
          <div class="account-security-note">
            密码仅在本机后端保存，列表和接口返回时只显示脱敏内容。
          </div>
        </div>
      </div>
      <template #footer>
        <el-button v-if="loginAccountForm.id" :disabled="loginAccountBusy" type="danger" plain
          @click="removeLoginAccount(loginAccounts.find(account => account.id === loginAccountForm.id)!)">删除</el-button>
        <el-button :disabled="loginAccountBusy" @click="loginAccountDialogVisible = false">关闭</el-button>
        <el-button type="primary" :loading="loginAccountBusy" @click="saveLoginAccount">保存账号</el-button>
      </template>
    </el-dialog>

    <!-- User Input Dialog -->
    <el-dialog v-model="userInputDialogVisible" title="请输入" width="400px"
      :close-on-click-modal="false" :close-on-press-escape="false" :show-close="false">
      <div class="user-input-dialog">
        <p class="input-prompt">{{ currentInputRequest?.prompt }}</p>
        <el-input v-model="userInputValue"
          :type="currentInputRequest?.input_type === 'password' ? 'password' : 'text'"
          :show-password="currentInputRequest?.input_type === 'password'"
          placeholder="请输入..." @keyup.enter="submitUserInput" />
      </div>
      <template #footer>
        <el-button @click="cancelUserInput">取消</el-button>
        <el-button type="primary" :disabled="!userInputValue" @click="submitUserInput">确定</el-button>
      </template>
    </el-dialog>

    <!-- Test Report Dialog -->
    <el-dialog v-model="planReportDialogVisible" title="测试报告" width="800px" destroy-on-close>
      <div v-if="testPlanReport" class="test-report-content">
        <div class="report-summary">
          <div class="summary-stat">
            <span class="value">{{ testPlanReport.summary.total_cases }}</span>
            <span class="label">用例总数</span>
          </div>
          <div class="summary-stat">
            <span class="value">{{ testPlanReport.summary.total_runs }}</span>
            <span class="label">执行次数</span>
          </div>
          <div class="summary-stat passed">
            <span class="value">{{ testPlanReport.summary.passed }}</span>
            <span class="label">通过</span>
          </div>
          <div class="summary-stat failed">
            <span class="value">{{ testPlanReport.summary.failed }}</span>
            <span class="label">失败</span>
          </div>
          <div class="summary-stat uncertain">
            <span class="value">{{ testPlanReport.summary.uncertain }}</span>
            <span class="label">待确认</span>
          </div>
          <div class="summary-stat uncertain">
            <span class="value">{{ testPlanReport.summary.review_required }}</span>
            <span class="label">需复核</span>
          </div>
          <div class="summary-stat">
            <span class="value">{{ testPlanReport.summary.pass_rate }}%</span>
            <span class="label">通过率</span>
          </div>
        </div>
        <div v-if="Object.keys(testPlanReport.summary.error_categories).length > 0" class="error-categories">
          <h4>错误分类</h4>
          <div class="category-tags">
            <el-tag v-for="(count, category) in testPlanReport.summary.error_categories" :key="category" type="danger" effect="plain">
              {{ category }}: {{ count }}
            </el-tag>
          </div>
        </div>
        <el-table :data="testPlanReport.cases" stripe max-height="400">
          <el-table-column prop="sequence" label="序号" width="60" />
          <el-table-column prop="case_name" label="用例名称" min-width="180" show-overflow-tooltip />
          <el-table-column label="结果" width="80">
            <template #default="{ row }">
              <el-tag :type="resultType(row.latest_result)" size="small">{{ row.latest_result }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="AI断言" width="130">
            <template #default="{ row }">
              <span>{{ assertionBrief(row) }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="latest_error_category" label="错误类型" width="120">
            <template #default="{ row }">
              <span v-if="row.latest_error_category" class="error-category">{{ row.latest_error_category }}</span>
              <span v-else>-</span>
            </template>
          </el-table-column>
          <el-table-column label="耗时" width="80">
            <template #default="{ row }">
              {{ row.latest_duration_ms ? `${(row.latest_duration_ms / 1000).toFixed(1)}s` : '-' }}
            </template>
          </el-table-column>
          <el-table-column label="操作" width="120">
            <template #default="{ row }">
              <el-button size="small" text type="success" @click="loadCheckpointPlan(row.id, row.case_name, row.target_app, row.steps, row.expected_result || ''); checkpointPlanCaseId = row.id">Checkpoint</el-button>
              <el-button v-if="row.latest_execution_id" size="small" text type="primary" @click="viewExecutionDetail(row.latest_execution_id)">详情</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
      <template #footer>
        <el-button @click="exportReport('json')">导出 JSON</el-button>
        <el-button @click="exportReport('html')">导出 HTML</el-button>
        <el-button @click="planReportDialogVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    <TestCaseExecutionReport v-model:visible="executionReportDialogVisible" :execution-id="selectedExecutionId" />

    <!-- Checkpoint Plan Dialog -->
    <el-dialog v-model="checkpointPlanCaseId" title="Checkpoint 执行计划" width="640px" destroy-on-close @close="checkpointPlan = null; checkpointPlanCaseId = null">
      <div v-if="checkpointPlanBusy" style="text-align: center; padding: 24px;">
        <el-icon class="is-loading" :size="24"><Loading /></el-icon>
        <span>加载中...</span>
      </div>
      <div v-else-if="checkpointPlan" class="checkpoint-plan">
        <div class="checkpoint-meta">
          <el-tag size="small">{{ checkpointPlan.platform }}</el-tag>
          <span>{{ checkpointPlan.target_app }}</span>
        </div>
        <div v-if="checkpointPlan.preconditions.length" class="checkpoint-section">
          <h4>前置条件</h4>
          <ul>
            <li v-for="(pre, i) in checkpointPlan.preconditions" :key="i">{{ pre }}</li>
          </ul>
        </div>
        <div class="checkpoint-section">
          <h4>Checkpoints ({{ checkpointPlan.checkpoints.length }})</h4>
          <div v-for="cp in checkpointPlan.checkpoints" :key="cp.id" class="checkpoint-card">
            <div class="checkpoint-header">
              <span class="checkpoint-id">{{ cp.id }}</span>
              <span class="checkpoint-goal">{{ cp.goal }}</span>
            </div>
            <div v-if="cp.success_signals.length" class="checkpoint-signals">
              <span class="signal-label success">成功信号:</span>
              <el-tag v-for="s in cp.success_signals" :key="s" size="small" type="success">{{ s }}</el-tag>
            </div>
            <div v-if="cp.failure_signals.length" class="checkpoint-signals">
              <span class="signal-label danger">失败信号:</span>
              <el-tag v-for="s in cp.failure_signals" :key="s" size="small" type="danger">{{ s }}</el-tag>
            </div>
            <div class="checkpoint-meta-row">
              <span>最大步数: {{ cp.max_steps }}</span>
              <span>允许动作: {{ cp.allowed_actions.join(', ') }}</span>
            </div>
          </div>
        </div>
        <div v-if="checkpointPlan.final_expectations.length" class="checkpoint-section">
          <h4>最终期望</h4>
          <ul>
            <li v-for="(exp, i) in checkpointPlan.final_expectations" :key="i">{{ exp }}</li>
          </ul>
        </div>
      </div>
      <template #footer>
        <el-button @click="checkpointPlanCaseId = null">关闭</el-button>
      </template>
    </el-dialog>

    <!-- 新建文档对话框 -->
    <el-dialog v-model="showCreateFolderDialog" title="新建测试用例文档" width="480px" destroy-on-close>
      <el-form label-width="100px">
        <el-form-item label="文档名称">
          <el-input v-model="newFolderName" placeholder="如：登录功能" />
        </el-form-item>
        <el-form-item label="需求摘要">
          <el-input v-model="newFolderSummary" type="textarea" :rows="3" placeholder="可选，描述该文档对应的功能需求" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateFolderDialog = false">取消</el-button>
        <el-button type="primary" @click="handleCreateFolder" :disabled="!newFolderName.trim()">确定</el-button>
      </template>
    </el-dialog>

    <!-- 批量移动到文档对话框 -->
    <el-dialog v-model="showMoveDialog" title="移动用例到文档" width="480px" destroy-on-close>
      <el-form label-width="100px">
        <el-form-item label="目标文档">
          <el-select v-model="moveTargetFolderId" placeholder="选择目标文档" style="width: 100%">
            <el-option
              v-for="folder in selectedPlan?.folders || []"
              :key="folder.id"
              :label="folder.name"
              :value="folder.id"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showMoveDialog = false">取消</el-button>
        <el-button type="primary" @click="handleBatchMove" :disabled="!moveTargetFolderId">确定</el-button>
      </template>
    </el-dialog>
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

.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  height: 48px;
  padding: 0 16px;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-nav);
  color: var(--text-primary);
  flex-shrink: 0;
}

.topbar-left {
  display: flex;
  align-items: center;
  gap: 16px;
  min-width: 0;
}

.page-title {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-inverse);
}

.device-info {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}

.device-info .label { color: var(--text-muted); }
.device-info .value { display: flex; align-items: center; gap: 6px; color: var(--text-primary); }
.device-info .value.empty { color: var(--text-muted); }

.topbar-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
}

.main-content {
  display: flex;
  flex: 1;
  min-width: 0;
  overflow: hidden;
}

.left-sidebar {
  display: flex;
  flex-direction: column;
  width: clamp(200px, 24vw, 260px);
  border-right: 1px solid var(--border-color);
  background: var(--bg-sidebar);
  color: var(--text-primary);
  flex-shrink: 0;
  overflow: hidden;
}

.sidebar-section {
  display: flex;
  flex-direction: column;
  border-bottom: 1px solid var(--border-color);
}

.sidebar-section:last-child { border-bottom: 0; flex: 1; overflow: hidden; }

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

.import-box { display: flex; flex-direction: column; gap: 8px; padding: 8px 12px 12px; }

.field-label { color: var(--text-muted); font-size: 11px; }
.required-mark { color: var(--el-color-danger); margin-right: 2px; font-weight: 600; }
.precondition-text {
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
  word-break: break-word;
  font-size: 12px;
  line-height: 1.5;
  color: var(--text-default, #e5e7eb);
}

.file-picker {
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

.file-picker:hover { border-color: var(--accent); background: var(--bg-tertiary); }
.file-picker span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.file-picker input { display: none; }

.ai-gen-box { display: flex; flex-direction: column; gap: 8px; padding: 8px 12px 12px; }
.ai-gen-progress { padding: 4px 0; }
.ai-gen-progress .el-steps--simple { padding: 8px 16px; }
.ai-gen-error { padding: 0; }

.plan-list { flex: 1; overflow: auto; padding: 4px 0; }

.plan-item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 8px 12px;
  border: 0;
  background: transparent;
  color: var(--text-primary);
  cursor: pointer;
  text-align: left;
}

.plan-item:hover, .plan-item.active { background: var(--bg-tertiary); }

.plan-info { display: flex; flex-direction: column; flex: 1; min-width: 0; gap: 2px; }

.plan-name {
  font-size: 12px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.plan-meta { color: var(--text-muted); font-size: 11px; }

.empty-sidebar {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 32px 16px;
  color: var(--text-muted);
  font-size: 12px;
}

.right-content { flex: 1; display: flex; flex-direction: column; min-width: 0; background: var(--bg-primary); overflow: hidden; }

.phone-panel {
  display: flex;
  flex-direction: column;
  width: clamp(260px, 28vw, 340px);
  flex-shrink: 0;
  gap: 10px;
  padding: 12px;
  border-left: 1px solid var(--border-color);
  background: var(--bg-sidebar);
  color: var(--text-primary);
}

.phone-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }
.phone-header div { display: flex; min-width: 0; flex-direction: column; gap: 3px; }
.phone-header strong { color: var(--text-primary); font-size: 13px; }
.phone-header span { overflow: hidden; color: var(--text-muted); font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }

.phone-screen {
  display: flex;
  flex: 1;
  min-height: 0;
  align-items: center;
  justify-content: center;
  position: relative;
  overflow: hidden;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  background: var(--bg-tertiary);
  touch-action: none;
  outline: none;
  cursor: default;
}

.phone-canvas,
.phone-video,
.phone-yume-host {
  display: block;
  max-width: 100%;
  max-height: 100%;
}

.phone-yume-host {
  display: flex;
  width: 100%;
  height: 100%;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}

.phone-yume-host :deep(canvas) {
  max-width: 100%;
  max-height: 100%;
  display: block;
}

.phone-video {
  width: auto;
  height: 100%;
  object-fit: contain;
  background: #000;
}

.phone-native-host {
  position: relative;
  width: 100%;
  height: 100%;
  min-height: 220px;
  overflow: hidden;
  background: #000;
}

.phone-state.native {
  position: absolute;
  inset: 0;
  background: rgba(0, 0, 0, 0.72);
  pointer-events: none;
}

.phone-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 18px;
  color: var(--text-muted);
  font-size: 12px;
  text-align: center;
}

.phone-state.error { color: var(--danger); }

.phone-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  color: var(--text-muted);
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 11px;
}

.phone-nav {
  display: flex;
  gap: 4px;
}

.phone-nav-btn {
  width: 26px;
  height: 22px;
  padding: 0;
  border: 1px solid var(--border-color);
  border-radius: 4px;
  background: var(--bg-primary);
  color: var(--text-secondary);
  font-size: 11px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
}

.phone-nav-btn:hover:not(:disabled) {
  background: var(--bg-tertiary);
  color: var(--text-primary);
}

.phone-nav-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.phone-notice { flex-shrink: 0; }

.empty-state { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 16px; height: 100%; color: var(--text-muted); }
.empty-state h2 { margin: 0; font-size: 20px; font-weight: 500; color: var(--text-primary); }
.empty-state p { margin: 0; font-size: 13px; }

.plan-detail { display: flex; flex-direction: column; height: 100%; padding: 16px; gap: 12px; overflow: hidden; }

.detail-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; flex-shrink: 0; }
.detail-header h2 { margin: 2px 0 4px; color: var(--text-primary); font-size: 20px; font-weight: 600; }

.eyebrow { margin: 0; color: var(--accent); font-size: 11px; font-weight: 700; letter-spacing: 0.3px; text-transform: uppercase; }
.plan-summary { margin: 0; color: var(--text-secondary); font-size: 12px; }
.detail-actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; }

.plan-alert { flex-shrink: 0; }
.alert-action { margin-left: 8px; padding: 0 4px; vertical-align: baseline; }

.case-table { flex: 1; min-height: 0; }

:deep(.el-table__row) {
  cursor: pointer;
}

.case-steps {
  max-height: 80px;
  margin: 0;
  overflow: auto;
  color: var(--text-primary);
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
}

.manual-case-form { display: flex; flex-direction: column; gap: 8px; }

.batch-field-row { display: flex; align-items: center; gap: 8px; }
.batch-field-row .el-select { flex: 1; min-width: 0; }

.manual-case-grid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 12px; }

.account-config-strip {
  display: flex; flex-shrink: 0; align-items: center; justify-content: space-between; gap: 12px;
  min-height: 34px; padding: 6px 10px; border: 1px solid var(--border-color); border-radius: 6px;
  background: var(--bg-sidebar); color: var(--text-secondary); font-size: 12px;
}

.account-strip-info, .account-strip-actions { display: flex; align-items: center; gap: 6px; min-width: 0; }
.account-strip-info strong { color: var(--text-primary); }

.login-account-layout { display: grid; grid-template-columns: minmax(190px, 0.55fr) minmax(0, 1fr); gap: 14px; min-height: 360px; }

.login-account-list { min-width: 0; overflow: hidden; border: 1px solid var(--border-color); border-radius: 6px; background: var(--bg-sidebar); }

.account-list-header {
  display: flex; align-items: center; justify-content: space-between; height: 34px; padding: 0 10px;
  border-bottom: 1px solid var(--border-color); color: var(--text-secondary); font-size: 12px;
}

.account-empty { padding: 18px 10px; color: var(--text-muted); font-size: 12px; text-align: center; }

.account-row {
  display: flex; flex-direction: column; width: 100%; gap: 3px; padding: 9px 10px;
  border: 0; border-bottom: 1px solid var(--border-color); background: transparent;
  color: var(--text-primary); cursor: pointer; text-align: left;
}

.account-row:hover, .account-row.active { background: var(--bg-tertiary); }
.account-name, .account-meta { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.account-name { font-size: 12px; font-weight: 600; }
.account-meta { color: var(--text-muted); font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 11px; }

.login-account-form { display: flex; min-width: 0; flex-direction: column; gap: 8px; }

.account-security-note {
  padding: 8px 10px; border-radius: 6px; background: var(--bg-sidebar);
  color: var(--text-muted); font-size: 12px; line-height: 1.5;
}

/* Test Report Styles */
.test-report-content { display: flex; flex-direction: column; gap: 16px; }

.report-summary { display: flex; gap: 16px; padding: 16px; background: var(--el-fill-color-light); border-radius: 8px; }

.summary-stat { display: flex; flex-direction: column; align-items: center; gap: 4px; flex: 1; }
.summary-stat .value { font-size: 24px; font-weight: 600; color: var(--el-text-color-primary); }
.summary-stat.passed .value { color: var(--el-color-success); }
.summary-stat.failed .value { color: var(--el-color-danger); }
.summary-stat.uncertain .value { color: var(--el-color-warning); }
.summary-stat .label { font-size: 12px; color: var(--el-text-color-secondary); }

.error-categories { padding: 12px; background: var(--el-color-danger-light-9); border-radius: 6px; }
.error-categories h4 { margin: 0 0 8px; font-size: 13px; color: var(--el-text-color-primary); }
.category-tags { display: flex; flex-wrap: wrap; gap: 8px; }
.error-category { color: var(--el-color-danger); font-size: 12px; }

.user-input-dialog { display: flex; flex-direction: column; gap: 16px; }
.input-prompt { margin: 0; font-size: 14px; color: var(--text-primary); line-height: 1.5; }

@media (max-width: 900px) {
  .main-content { display: grid; grid-template-columns: minmax(0, 1fr); grid-template-rows: auto minmax(0, 1fr) minmax(220px, 34vh); }
  .left-sidebar { width: auto; max-height: 220px; border-right: 0; border-bottom: 1px solid var(--border-color); }
  .phone-panel { width: auto; min-width: 0; min-height: 220px; border-top: 1px solid var(--border-color); border-left: 0; }
}

@media (max-width: 720px) {
  .topbar { height: auto; min-height: 48px; flex-wrap: wrap; align-items: flex-start; padding: 8px 10px; }
  .topbar-left { flex-wrap: wrap; gap: 8px; }
  .detail-header { flex-direction: column; align-items: stretch; }
  .detail-actions { justify-content: flex-start; }
  .plan-detail { padding: 10px; }
  .main-content { grid-template-rows: minmax(130px, auto) minmax(0, 1fr) minmax(180px, 30vh); }
  .phone-panel { padding: 8px; }
  .manual-case-grid { grid-template-columns: minmax(0, 1fr); }
  .login-account-layout { grid-template-columns: minmax(0, 1fr); }
}

.run-log-panel {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px 16px;
  background: var(--bg-primary);
}

.run-log-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  color: var(--text-primary);
  font-size: 13px;
  font-weight: 600;
}

.run-log-phases {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.run-log-phase {
  min-width: 0;
  padding: 10px;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  background: var(--bg-sidebar);
}

.run-log-phase h4 {
  margin: 0 0 8px;
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 600;
}

.run-log-lines {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 180px;
  overflow: auto;
}

.run-log-line {
  display: grid;
  grid-template-columns: 70px minmax(0, 1fr) auto;
  gap: 8px;
  color: var(--text-secondary);
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 11px;
  line-height: 1.45;
}

.run-log-line.error {
  color: var(--el-color-danger);
}

.run-log-line.result {
  color: var(--el-color-success);
}

.run-log-line.waiting {
  color: var(--el-color-warning);
}

.run-log-time {
  color: var(--text-muted);
}

.run-log-message {
  min-width: 0;
  overflow-wrap: anywhere;
}

@media (max-width: 720px) {
  .run-log-phases { grid-template-columns: minmax(0, 1fr); }
}

.expand-loading {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 16px;
  color: var(--text-muted);
}

.expand-content {
  padding: 12px 16px;
}

.expand-header {
  display: flex;
  gap: 24px;
  margin-bottom: 12px;
  font-size: 13px;
  color: var(--text-secondary);
}

.expand-header span {
  display: flex;
  align-items: center;
  gap: 6px;
}

.expand-trace {
  color: var(--el-color-primary);
  font-size: 12px;
}

.expand-trace code {
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  background: var(--el-fill-color);
  padding: 1px 4px;
  border-radius: 3px;
}

.resume-row {
  display: flex;
  justify-content: center;
  padding: 8px 0;
}

.expand-steps h4 {
  margin: 0 0 8px 0;
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary);
}

.steps-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.step-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 8px 10px;
  background: var(--bg-secondary);
  border-radius: 4px;
  font-size: 12px;
}

.step-item.step-failed {
  background: color-mix(in srgb, var(--danger) 8%, transparent);
  border-left: 3px solid var(--el-color-danger);
}

.step-num {
  flex-shrink: 0;
  width: 20px;
  height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--el-color-primary);
  color: var(--text-inverse);
  border-radius: 50%;
  font-size: 11px;
  font-weight: 600;
}

.step-failed .step-num {
  background: var(--el-color-danger);
}

.step-icon {
  flex-shrink: 0;
  font-size: 14px;
}

.step-time {
  flex-shrink: 0;
  font-size: 11px;
  color: var(--text-muted);
  font-family: ui-monospace, monospace;
  min-width: 70px;
}

.step-action {
  flex-shrink: 0;
  font-weight: 500;
  color: var(--text-primary);
  min-width: 80px;
}

.step-msg {
  flex: 1;
  color: var(--text-secondary);
  word-break: break-word;
}

.step-app {
  flex-shrink: 0;
  font-size: 11px;
  color: var(--text-muted);
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.step-screenshot {
  flex-shrink: 0;
}

.step-thumb {
  width: 48px;
  height: 36px;
  border-radius: 4px;
  cursor: pointer;
  object-fit: cover;
}

.expand-empty {
  padding: 16px;
  color: var(--text-muted);
  font-size: 13px;
}

/* Checkpoint plan styles */
.checkpoint-plan {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.checkpoint-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--text-primary);
}

.checkpoint-section h4 {
  margin: 0 0 8px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
}

.checkpoint-section ul {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
  color: var(--text-primary);
}

.checkpoint-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  background: var(--bg-secondary);
  margin-bottom: 8px;
}

.checkpoint-header {
  display: flex;
  align-items: center;
  gap: 8px;
}

.checkpoint-id {
  font-size: 12px;
  font-weight: 600;
  color: var(--accent);
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
}

.checkpoint-goal {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary);
}

.checkpoint-signals {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.signal-label {
  font-size: 12px;
  font-weight: 500;
}

.signal-label.success { color: var(--el-color-success); }
.signal-label.danger { color: var(--el-color-danger); }

.checkpoint-meta-row {
  display: flex;
  gap: 16px;
  font-size: 11px;
  color: var(--text-muted);
}
</style>
