import axios from 'axios'

// Detect if running in Electron
const electronAPI = typeof window !== 'undefined' ? (window as any).electronAPI : undefined
const isElectron = Boolean(electronAPI?.isElectron)
const configuredApiBaseUrl = normalizeBaseUrl(import.meta.env.VITE_API_BASE_URL)
const defaultApiBaseUrl = 'http://127.0.0.1:8000'

export let apiBaseUrl = configuredApiBaseUrl ?? defaultApiBaseUrl

export interface DeviceInfo {
  udid: string
  status: 'online' | 'offline' | 'unauthorized' | 'unknown'
  platform: 'android' | 'ios' | 'harmony'
  model?: string | null
  product?: string | null
  transport_id?: string | null
  os_version?: string | null
  stream_provider?: string | null
  stream_available?: boolean
  stream_note?: string | null
  wda_url?: string | null
  wda_running?: boolean
  name?: string | null
}

export interface ScreenshotResponse {
  udid: string
  file_path: string
  url: string
  created_at: string
}

export interface ScrcpyStartResponse {
  udid: string
  pid: number
  command: string[]
}

export interface DeviceScreenSizeResponse {
  udid: string
  width: number
  height: number
}

export interface DeviceControlResponse {
  udid: string
  command: string
  stdout: string
  stderr: string
  success: boolean
}

export interface VisualClickResponse {
  udid: string
  found: boolean
  x?: number | null
  y?: number | null
  score: number
  width?: number | null
  height?: number | null
  text?: string | null
  template_path?: string | null
  message: string
}

export interface DeviceUiBounds {
  left: number
  top: number
  right: number
  bottom: number
  width: number
  height: number
  center_x: number
  center_y: number
}

export interface DeviceUiElement {
  platform: string
  package?: string | null
  class_name: string
  text?: string | null
  content_desc?: string | null
  resource_id?: string | null
  clickable: boolean
  enabled: boolean
  bounds: DeviceUiBounds
  xpath: string
  hierarchy_xpath?: string | null
  selector: Record<string, string>
  input_capable?: boolean
  depth: number
  index: number
}

export interface DeviceUiLocateResponse {
  udid: string
  found: boolean
  element?: DeviceUiElement | null
  generated_code: string
  message: string
}

export const api = axios.create({
  baseURL: apiBaseUrl,
  timeout: 30000,
})

// Request deduplication - avoid duplicate concurrent requests
const pendingRequests = new Map<string, Promise<any>>()

export async function dedupeRequest<T>(key: string, request: () => Promise<T>): Promise<T> {
  if (pendingRequests.has(key)) {
    return pendingRequests.get(key) as Promise<T>
  }
  const promise = request().finally(() => pendingRequests.delete(key))
  pendingRequests.set(key, promise)
  return promise
}

export async function initializeApiBaseUrl(): Promise<void> {
  if (
    configuredApiBaseUrl
    && await isBackendHealthy(configuredApiBaseUrl)
    && await isBackendCompatible(configuredApiBaseUrl)
  ) {
    setApiBaseUrl(configuredApiBaseUrl)
    return
  }
  if (configuredApiBaseUrl) {
    console.warn(`Configured API base URL is not healthy: ${configuredApiBaseUrl}. Trying local backend discovery.`)
  }

  const backendUrl = await resolveApiBaseUrl()
  setApiBaseUrl(backendUrl)
}

async function resolveApiBaseUrl(): Promise<string> {
  const electronBackendUrl = await getElectronBackendUrl()
  if (electronBackendUrl && await isBackendHealthy(electronBackendUrl) && await isBackendCompatible(electronBackendUrl)) {
    return electronBackendUrl
  }

  const candidates = buildBackendCandidates(electronBackendUrl)
  for (const candidate of candidates) {
    if (await isBackendHealthy(candidate) && await isBackendCompatible(candidate)) {
      return candidate
    }
  }

  for (const candidate of candidates) {
    if (await isBackendHealthy(candidate)) {
      return candidate
    }
  }

  console.warn(`No healthy backend was discovered, using fallback API base URL: ${defaultApiBaseUrl}`)
  return defaultApiBaseUrl
}

async function getElectronBackendUrl(): Promise<string | null> {
  if (!isElectron || typeof electronAPI?.getBackendUrl !== 'function') {
    return null
  }
  try {
    const backendUrl = await electronAPI.getBackendUrl()
    return normalizeBaseUrl(backendUrl)
  } catch (error) {
    console.warn('Failed to read Electron backend URL, trying local backend discovery.', error)
    return null
  }
}

function setApiBaseUrl(baseUrl: string) {
  apiBaseUrl = baseUrl
  api.defaults.baseURL = baseUrl
}

function buildBackendCandidates(preferredUrl?: string | null): string[] {
  const envPorts = String(import.meta.env.VITE_API_PORTS ?? '')
    .split(',')
    .map(value => Number(value.trim()))
    .filter(port => Number.isInteger(port) && port > 0)
  const ports = envPorts.length > 0 ? envPorts : [8000, 8001, 8002, 8003, 8004, 8005, 8010, 8080]
  const hosts = ['127.0.0.1', 'localhost']
  const candidates = [
    preferredUrl,
    ...ports.flatMap(port => hosts.map(host => `http://${host}:${port}`)),
  ]
  return [...new Set(candidates.filter(Boolean).map(value => normalizeBaseUrl(String(value))))] as string[]
}

function normalizeBaseUrl(value: string | null | undefined): string | null {
  const trimmed = value?.trim()
  if (!trimmed) return null
  return trimmed.replace(/\/+$/, '')
}

async function isBackendHealthy(baseUrl: string): Promise<boolean> {
  const controller = new AbortController()
  const timer = window.setTimeout(() => controller.abort(), 800)
  try {
    const response = await fetch(`${baseUrl}/api/health`, {
      method: 'GET',
      signal: controller.signal,
      cache: 'no-store',
    })
    if (!response.ok) return false
    const payload = await response.json().catch(() => null)
    return payload?.status === 'ok'
  } catch {
    return false
  } finally {
    window.clearTimeout(timer)
  }
}

async function isBackendCompatible(baseUrl: string): Promise<boolean> {
  const controller = new AbortController()
  const timer = window.setTimeout(() => controller.abort(), 1000)
  try {
    const [streamResponse, pythonEnvResponse] = await Promise.all([
      fetch(`${baseUrl}/api/devices/stream/capabilities`, {
        method: 'GET',
        signal: controller.signal,
        cache: 'no-store',
      }),
      fetch(`${baseUrl}/api/scripts/python-envs`, {
        method: 'GET',
        signal: controller.signal,
        cache: 'no-store',
      }),
    ])
    if (!streamResponse.ok || !pythonEnvResponse.ok) return false
    const streamPayload = await streamResponse.json().catch(() => null)
    const pythonEnvPayload = await pythonEnvResponse.json().catch(() => null)
    const providers = streamPayload?.android?.providers
    return (
      Array.isArray(providers)
      && providers.includes('scrcpy-webcodecs')
      && typeof pythonEnvPayload?.current === 'string'
      && Array.isArray(pythonEnvPayload?.envs)
    )
  } catch {
    return false
  } finally {
    window.clearTimeout(timer)
  }
}

export function getAssetUrl(path: string): string {
  if (path.startsWith('http')) {
    return path
  }
  return `${apiBaseUrl}${path}`
}

export async function fetchDevices(): Promise<DeviceInfo[]> {
  const response = await api.get<DeviceInfo[]>('/api/devices')
  return response.data
}

export interface DeviceConnectResponse {
  udid: string
  success: boolean
  message: string
}

export interface DeviceDisconnectResponse {
  address: string
  success: boolean
  message: string
}

export async function connectDevice(address: string): Promise<DeviceConnectResponse> {
  const response = await api.post<DeviceConnectResponse>('/api/devices/connect', { address })
  return response.data
}

export async function disconnectDevice(address: string): Promise<DeviceDisconnectResponse> {
  const response = await api.post<DeviceDisconnectResponse>(`/api/devices/disconnect/${encodeURIComponent(address)}`)
  return response.data
}

export async function captureDeviceScreenshot(
  udid: string,
  options: { platform?: string; wdaUrl?: string | null } = {},
): Promise<ScreenshotResponse> {
  const response = await api.post<ScreenshotResponse>(
    `/api/devices/${encodeURIComponent(udid)}/screenshot`,
    undefined,
    {
      params: {
        platform: options.platform,
        wda_url: options.wdaUrl,
      },
    },
  )
  return response.data
}

export interface ObservationFrame {
  type: 'observation_frame'
  udid: string
  image_base64: string
  mime_type: string
  width: number
  height: number
  size_bytes: number
  timestamp: string
}

export async function getDeviceObservationScreenshot(
  udid: string,
  options: { maxSize?: number; platform?: string } = {},
): Promise<ObservationFrame> {
  const response = await api.get<ObservationFrame>(
    `/api/devices/${encodeURIComponent(udid)}/screenshot/observe`,
    {
      params: {
        max_size: options.maxSize ?? 720,
        platform: options.platform ?? 'android',
      },
    },
  )
  return response.data
}

export async function getDeviceScreenSize(udid: string): Promise<DeviceScreenSizeResponse> {
  const response = await api.get<DeviceScreenSizeResponse>(`/api/devices/${encodeURIComponent(udid)}/screen-size`)
  return response.data
}

export async function startScrcpyMirror(udid: string, maxSize = 1280, maxFps = 30): Promise<ScrcpyStartResponse> {
  const response = await api.post<ScrcpyStartResponse>(
    `/api/devices/${encodeURIComponent(udid)}/scrcpy/start`,
    undefined,
    { params: { max_size: maxSize, max_fps: maxFps } },
  )
  return response.data
}

export async function stopScrcpyMirror(udid: string): Promise<void> {
  await api.post(`/api/devices/${encodeURIComponent(udid)}/scrcpy/stop`)
}

export interface CurrentAppResponse {
  udid: string
  package_name: string | null
  activity: string | null
  raw_output: string
}

export async function getCurrentApp(udid: string): Promise<CurrentAppResponse> {
  const response = await api.get<CurrentAppResponse>(`/api/devices/${encodeURIComponent(udid)}/current-app`)
  return response.data
}

export async function runDeviceControlCommand(udid: string, command: string): Promise<DeviceControlResponse> {
  const response = await api.post<DeviceControlResponse>(`/api/devices/${encodeURIComponent(udid)}/control`, {
    command,
  })
  return response.data
}

export async function tapDevicePoint(
  udid: string,
  payload: { x: number; y: number; platform?: string; wda_url?: string | null },
): Promise<{ udid: string; platform: string; x: number; y: number; success: boolean }> {
  const response = await api.post<{ udid: string; platform: string; x: number; y: number; success: boolean }>(
    `/api/devices/${encodeURIComponent(udid)}/tap`,
    payload,
  )
  return response.data
}

export async function pressDeviceKey(
  udid: string,
  keycode: number,
  platform = 'android',
): Promise<{ udid: string; keycode: number; platform: string; success: boolean }> {
  const response = await api.post<{ udid: string; keycode: number; platform: string; success: boolean }>(
    `/api/devices/${encodeURIComponent(udid)}/key`,
    null,
    { params: { keycode, platform } },
  )
  return response.data
}

export async function swipeDevice(
  udid: string,
  x1: number,
  y1: number,
  x2: number,
  y2: number,
  durationMs = 300,
  platform = 'android',
): Promise<{ udid: string; success: boolean }> {
  const response = await api.post<{ udid: string; success: boolean }>(
    `/api/devices/${encodeURIComponent(udid)}/swipe`,
    null,
    { params: { x1, y1, x2, y2, duration_ms: durationMs, platform } },
  )
  return response.data
}

export async function inputDeviceText(
  udid: string,
  text: string,
  platform = 'android',
): Promise<{ udid: string; success: boolean }> {
  const response = await api.post<{ udid: string; success: boolean }>(
    `/api/devices/${encodeURIComponent(udid)}/input-text`,
    null,
    { params: { text, platform } },
  )
  return response.data
}

export async function touchDown(
  udid: string,
  x: number,
  y: number,
  platform = 'android',
): Promise<{ udid: string; x: number; y: number; action: string; success: boolean }> {
  const response = await api.post<{ udid: string; x: number; y: number; action: string; success: boolean }>(
    `/api/devices/${encodeURIComponent(udid)}/touch/down`,
    null,
    { params: { x, y, platform } },
  )
  return response.data
}

export async function touchMove(
  udid: string,
  x: number,
  y: number,
  platform = 'android',
): Promise<{ udid: string; x: number; y: number; action: string; success: boolean }> {
  const response = await api.post<{ udid: string; x: number; y: number; action: string; success: boolean }>(
    `/api/devices/${encodeURIComponent(udid)}/touch/move`,
    null,
    { params: { x, y, platform } },
  )
  return response.data
}

export async function touchUp(
  udid: string,
  x: number,
  y: number,
  platform = 'android',
): Promise<{ udid: string; x: number; y: number; action: string; success: boolean }> {
  const response = await api.post<{ udid: string; x: number; y: number; action: string; success: boolean }>(
    `/api/devices/${encodeURIComponent(udid)}/touch/up`,
    null,
    { params: { x, y, platform } },
  )
  return response.data
}

export async function clickDeviceText(udid: string, text: string, contains = true): Promise<VisualClickResponse> {
  const response = await api.post<VisualClickResponse>(`/api/devices/${encodeURIComponent(udid)}/visual/text-click`, {
    text,
    contains,
  })
  return response.data
}

export async function clickDeviceTemplate(
  udid: string,
  file: File,
  threshold = 0.92,
  saveTemplate = false,
): Promise<VisualClickResponse> {
  const form = new FormData()
  form.append('file', file)
  const response = await api.post<VisualClickResponse>(
    `/api/devices/${encodeURIComponent(udid)}/visual/template-click`,
    form,
    {
      headers: { 'Content-Type': 'multipart/form-data' },
      params: { threshold, save_template: saveTemplate },
    },
  )
  return response.data
}

export async function locateDeviceUiElement(
  udid: string,
  payload: {
    x: number
    y: number
    platform?: string
    package_name?: string | null
    strict_xpath_only?: boolean
    cache_ttl_ms?: number
    wda_url?: string | null
  },
): Promise<DeviceUiLocateResponse> {
  const response = await api.post<DeviceUiLocateResponse>(`/api/devices/${encodeURIComponent(udid)}/ui/locate`, payload)
  return response.data
}

export interface ScreenWebSocketOptions {
  platform?: string
  provider?: string
  maxFps?: number
  maxSize?: number
  wdaUrl?: string
  control?: boolean
}

export function getDeviceScreenWebSocketUrl(udid: string, options: ScreenWebSocketOptions = {}): string {
  const baseUrl = new URL(apiBaseUrl)
  baseUrl.protocol = baseUrl.protocol === 'https:' ? 'wss:' : 'ws:'
  baseUrl.pathname = `/api/devices/${encodeURIComponent(udid)}/screen`
  const params = new URLSearchParams({
    platform: options.platform ?? 'android',
    provider: options.provider ?? 'auto',
    max_fps: String(options.maxFps ?? 20),
    max_size: String(options.maxSize ?? 1280),
    control: String(options.control ?? true),
  })
  if (options.wdaUrl) {
    params.append('wda_url', options.wdaUrl)
  }
  baseUrl.search = params.toString()
  return baseUrl.toString()
}

export function getDeviceControlWebSocketUrl(udid: string): string {
  const baseUrl = new URL(apiBaseUrl)
  baseUrl.protocol = baseUrl.protocol === 'https:' ? 'wss:' : 'ws:'
  baseUrl.pathname = `/api/devices/${encodeURIComponent(udid)}/control/live`
  return baseUrl.toString()
}

export interface TestCaseFolder {
  id: number
  plan_id: number
  name: string
  requirement_summary?: string | null
  source_type?: string | null
  source_filename?: string | null
  sequence: number
  total_cases: number
  created_at?: string | null
}

export interface TestCaseFolderCreate {
  name: string
  requirement_summary?: string | null
  source_type?: string | null
  source_filename?: string | null
}

export interface TestCaseFolderUpdate {
  name?: string | null
  requirement_summary?: string | null
}

export interface ImportedTestCase {
  id: number
  plan_id: number
  folder_id?: number | null
  folder_name?: string | null
  sequence: number
  system_name?: string | null
  module?: string | null
  case_name: string
  precondition?: string | null
  steps: string[]
  expected_result?: string | null
  requirement_id?: string | null
  case_type?: string | null
  priority?: string | null
  target_app: string
  test_module?: string | null
  run_count: number
  latest_result: 'pending' | 'running' | 'passed' | 'failed'
  latest_result_note: string
}

export interface ImportedTestCaseCreateRequest {
  case_name: string
  steps: string[]
  expected_result: string
  folder_id?: number | null
  system_name?: string | null
  module?: string | null
  precondition?: string | null
  requirement_id?: string | null
  case_type?: string | null
  priority?: string | null
  target_app: string
  test_module?: string | null
}

export interface TestPlanProject {
  id: number
  name: string
  source_filename?: string | null
  total_cases: number
  imported_at: string
  folders?: TestCaseFolder[]
  cases: ImportedTestCase[]
}

export interface TestPlanListItem {
  id: number
  name: string
  source_filename?: string | null
  total_cases: number
  imported_at: string
}

export interface TestCaseExecution {
  id: number
  plan_id: number
  case_id: number
  run_index: number
  device_udid?: string | null
  run_result: 'pending' | 'running' | 'passed' | 'failed' | 'uncertain'
  result_note: string
  error_category?: string | null
  action_trace: Record<string, unknown>[]
  started_at: string
  ended_at?: string | null
  duration_ms?: number | null
}

export interface ExecutionDetailReport {
  execution_id: number
  case_name: string
  trace_id?: string | null
  result: string
  result_note?: string | null
  error_category?: string | null
  device_udid?: string | null
  started_at: string | null
  ended_at: string | null
  duration_ms: number | null
  assertion_result?: {
    verdict?: string
    confidence?: number | null
    reason?: string | null
    evidence?: string[]
    failed_expectations?: string[]
    [key: string]: unknown
  } | null
  screenshots: Array<{
    step: number
    url: string | null
    current_app: string | null
    timestamp: string | null
  }>
  action_summary: Array<{
    step: number
    action_type: string
    message: string
    success: boolean
    timestamp: string | null
    current_app: string | null
    screenshot_url: string | null
  }>
  error_details: Array<Record<string, unknown>>
  full_trace: Record<string, unknown>[] | Record<string, unknown>
  [key: string]: unknown
}

export interface TestPlanReport {
  plan_id: number
  plan_name?: string
  generated_at?: string
  summary: {
    total_cases: number
    total_runs: number
    passed: number
    failed: number
    uncertain: number
    review_required: number
    pass_rate: number
    error_categories: Record<string, number>
    [key: string]: unknown
  }
  cases: Array<{
    case_id: number
    sequence: number
    case_name: string
    target_app?: string | null
    test_module?: string | null
    run_count: number
    latest_result: string
    latest_result_note?: string | null
    latest_error_category?: string | null
    latest_duration_ms?: number | null
    latest_execution_id?: number | null
    latest_assertion?: {
      verdict?: string
      confidence?: number | null
      [key: string]: unknown
    } | null
    [key: string]: unknown
  }>
}

export interface TestCaseRunStreamEvent {
  event: 'log' | 'error' | 'result' | 'need_user' | 'batch_start' | 'case_start' | 'batch_result' | string
  type?: string
  phase: 'device_check' | 'precondition' | 'execution' | 'report' | string
  timestamp?: string
  message?: string
  case_id?: number
  case_name?: string
  plan_id?: number
  case_index?: number
  total_cases?: number
  execution_id?: number
  trace_id?: string
  run_result?: TestCaseExecution['run_result']
  result_note?: string
  error_category?: string | null
  report_url?: string
  report_folder_url?: string
  summary_url?: string
  duration_ms?: number | null
  [key: string]: unknown
}

export interface TestCaseRunPayload {
  device_udid?: string | null
  device_platform?: DeviceInfo['platform'] | null
  client_run_id?: string | null
}

export interface BatchRunResponse {
  plan_id: number
  total_cases: number
  executions: TestCaseExecution[]
}

export interface LoginAccount {
  id: number
  platform: string
  label: string
  login_id: string
  password_masked: string
  note?: string | null
  use_for_autoglm: boolean
  created_at: string
  updated_at?: string | null
}

export interface LoginAccountCreateRequest {
  platform: string
  label: string
  login_id: string
  password: string
  note?: string | null
  use_for_autoglm?: boolean
}

export type LoginAccountUpdateRequest = LoginAccountCreateRequest

export async function fetchTestPlans(): Promise<TestPlanListItem[]> {
  const response = await api.get<TestPlanListItem[]>('/api/test-plans')
  return response.data
}

export async function fetchLoginAccounts(): Promise<LoginAccount[]> {
  const response = await api.get<LoginAccount[]>('/api/login-accounts')
  return response.data
}

export async function createLoginAccount(payload: LoginAccountCreateRequest): Promise<LoginAccount> {
  const response = await api.post<LoginAccount>('/api/login-accounts', payload)
  return response.data
}

export async function updateLoginAccount(accountId: number, payload: LoginAccountUpdateRequest): Promise<LoginAccount> {
  const response = await api.put<LoginAccount>(`/api/login-accounts/${accountId}`, payload)
  return response.data
}

export async function deleteLoginAccount(accountId: number): Promise<void> {
  await api.delete(`/api/login-accounts/${accountId}`)
}

export async function fetchTestPlan(planId: number): Promise<TestPlanProject> {
  const response = await api.get<TestPlanProject>(`/api/test-plans/${planId}`)
  return response.data
}

export async function fetchTestPlanReport(planId: number): Promise<TestPlanReport> {
  const response = await api.get<TestPlanReport>(`/api/test-plans/${planId}/report`)
  return response.data
}

export async function exportTestPlanReport(
  planId: number,
  format: 'json' | 'html',
): Promise<{ filename: string; html?: string; report?: TestPlanReport }> {
  const response = await api.get<{ filename: string; html?: string; report?: TestPlanReport }>(
    `/api/test-plans/${planId}/export`,
    { params: { format } },
  )
  return response.data
}

export async function fetchExecutionDetailReport(executionId: number): Promise<ExecutionDetailReport> {
  const response = await api.get<ExecutionDetailReport>(`/api/test-plans/executions/${executionId}/report`)
  return response.data
}

export async function exportExecutionReport(
  executionId: number,
  format: 'json' | 'html',
): Promise<{ filename: string; html?: string; report?: ExecutionDetailReport }> {
  const response = await api.get<{ filename: string; html?: string; report?: ExecutionDetailReport }>(
    `/api/test-plans/executions/${executionId}/export`,
    { params: { format } },
  )
  return response.data
}

export async function importTestPlan(file: File, projectName: string): Promise<TestPlanProject> {
  const form = new FormData()
  form.append('project_name', projectName)
  form.append('file', file)
  const response = await api.post<TestPlanProject>('/api/test-plans/import', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return response.data
}

export interface RequirementAnalysisResponse {
  id: number
  name: string
  source_filename: string | null
  total_cases: number
  imported_at: string
  cases: ImportedTestCase[]
  generation_summary: {
    raw_text_length: number
    initial_case_count: number
    refined_case_count: number
    final_case_count: number
  }
}

export async function generateFromRequirement(
  file: File,
  projectName: string,
  targetApp: string,
): Promise<RequirementAnalysisResponse> {
  const form = new FormData()
  form.append('project_name', projectName)
  form.append('target_app', targetApp)
  form.append('file', file)
  const response = await api.post<RequirementAnalysisResponse>(
    '/api/test-plans/generate-from-requirement',
    form,
    {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 180000, // 3 minutes for AI generation (two DeepSeek calls)
    },
  )
  return response.data
}

export async function createImportedTestCase(
  planId: number,
  payload: ImportedTestCaseCreateRequest,
): Promise<ImportedTestCase> {
  const response = await api.post<ImportedTestCase>(`/api/test-plans/${planId}/cases`, payload)
  return response.data
}

export interface BatchUpdateCasesRequest {
  case_ids: number[]
  system_name?: string | null
  module?: string | null
  target_app?: string | null
  test_module?: string | null
}

export async function batchUpdateImportedTestCases(
  planId: number,
  payload: BatchUpdateCasesRequest,
): Promise<{ updated: number }> {
  const response = await api.post<{ updated: number }>(`/api/test-plans/${planId}/cases/batch-update`, payload)
  return response.data
}

export async function deleteTestPlan(planId: number): Promise<{ message: string }> {
  const response = await api.delete<{ message: string }>(`/api/test-plans/${planId}`)
  return response.data
}

export async function deleteImportedTestCase(caseId: number): Promise<{ message: string }> {
  const response = await api.delete<{ message: string }>(`/api/test-plans/cases/${caseId}`)
  return response.data
}

// ── Test Case Folder (Document) API ──────────────────────────────────────────

export async function createTestCaseFolder(planId: number, data: TestCaseFolderCreate): Promise<TestCaseFolder> {
  const response = await api.post<TestCaseFolder>(`/api/folders/plans/${planId}/folders`, data)
  return response.data
}

export async function listTestCaseFolders(planId: number): Promise<TestCaseFolder[]> {
  const response = await api.get<TestCaseFolder[]>(`/api/folders/plans/${planId}/folders`)
  return response.data
}

export async function updateTestCaseFolder(folderId: number, data: TestCaseFolderUpdate): Promise<TestCaseFolder> {
  const response = await api.put<TestCaseFolder>(`/api/folders/folders/${folderId}`, data)
  return response.data
}

export async function deleteTestCaseFolder(folderId: number): Promise<{ message: string }> {
  const response = await api.delete<{ message: string }>(`/api/folders/folders/${folderId}`)
  return response.data
}

export async function batchMoveCasesToFolder(caseIds: number[], targetFolderId: number): Promise<{ message: string }> {
  const response = await api.post<{ message: string }>('/api/folders/cases/batch-move', {
    case_ids: caseIds,
    target_folder_id: targetFolderId,
  })
  return response.data
}

export async function runImportedTestCase(
  caseId: number,
  deviceUdid?: string,
  devicePlatform?: DeviceInfo['platform'],
): Promise<TestCaseExecution> {
  const response = await api.post<TestCaseExecution>(
    `/api/test-plans/cases/${caseId}/run`,
    buildRunPayload(deviceUdid, devicePlatform),
  )
  return response.data
}

export async function runImportedTestCaseStream(
  caseId: number,
  payload: TestCaseRunPayload,
  onEvent: (event: TestCaseRunStreamEvent) => void,
  signal?: AbortSignal,
): Promise<TestCaseRunStreamEvent | null> {
  return readRunStream(`${apiBaseUrl}/api/test-plans/cases/${caseId}/run/stream`, payload, onEvent, signal)
}

export async function runImportedTestPlanStream(
  planId: number,
  payload: TestCaseRunPayload,
  onEvent: (event: TestCaseRunStreamEvent) => void,
  signal?: AbortSignal,
): Promise<TestCaseRunStreamEvent | null> {
  return readRunStream(`${apiBaseUrl}/api/test-plans/${planId}/run/stream`, payload, onEvent, signal)
}

export async function cancelTestRun(clientRunId: string): Promise<void> {
  await api.post(`/api/test-plans/runs/${encodeURIComponent(clientRunId)}/cancel`)
}

export async function resumeTestRun(clientRunId: string): Promise<void> {
  await api.post(`/api/test-plans/runs/${encodeURIComponent(clientRunId)}/resume`)
}

async function readRunStream(
  url: string,
  payload: TestCaseRunPayload,
  onEvent: (event: TestCaseRunStreamEvent) => void,
  signal?: AbortSignal,
): Promise<TestCaseRunStreamEvent | null> {
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    signal,
  })
  if (!response.ok) {
    const message = await response.text()
    throw new Error(message || `流式执行失败：${response.status}`)
  }
  if (!response.body) {
    throw new Error('浏览器不支持读取流式响应')
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  let finalEvent: TestCaseRunStreamEvent | null = null

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() ?? ''
    for (const line of lines) {
      const event = parseRunStreamLine(line)
      if (!event) continue
      onEvent(event)
      if (event.event === 'result' || event.event === 'batch_result') finalEvent = event
    }
  }

  const lastEvent = parseRunStreamLine(buffer)
  if (lastEvent) {
    onEvent(lastEvent)
    if (lastEvent.event === 'result' || lastEvent.event === 'batch_result') finalEvent = lastEvent
  }
  return finalEvent
}

export async function runImportedTestPlan(
  planId: number,
  deviceUdid?: string,
  devicePlatform?: DeviceInfo['platform'],
): Promise<BatchRunResponse> {
  const response = await api.post<BatchRunResponse>(
    `/api/test-plans/${planId}/run`,
    buildRunPayload(deviceUdid, devicePlatform),
  )
  return response.data
}

function buildRunPayload(deviceUdid?: string, devicePlatform?: DeviceInfo['platform']): TestCaseRunPayload {
  return {
    device_udid: deviceUdid || null,
    device_platform: devicePlatform || null,
    client_run_id: null,
  }
}

function parseRunStreamLine(line: string): TestCaseRunStreamEvent | null {
  const value = line.trim()
  if (!value) return null
  try {
    return JSON.parse(value) as TestCaseRunStreamEvent
  } catch {
    return {
      event: 'log',
      phase: 'execution',
      message: value,
    }
  }
}

// ── Scripts ──────────────────────────────────────────────────────────────────

export interface ScriptFile {
  name: string
  path: string
  size: number
  modified_at: string
  platform?: string | null
}

export interface ScriptContent {
  content: string
}

export interface ScriptRunResult {
  name: string
  stdout: string
  stderr: string
  returncode: number
  duration_ms: number
}

export interface ScriptRunStreamStart {
  run_id: string
  python_path: string
}

export interface PythonEnvInfo {
  name: string
  path: string
}

export interface PythonEnvsResponse {
  current: string
  default: string
  envs: PythonEnvInfo[]
}

export interface FileTreeItem {
  name: string
  path: string
  type: 'file' | 'folder'
  size?: number | null
  modified_at?: string | null
  children?: FileTreeItem[] | null
  platform?: string | null
}

export async function fetchScripts(): Promise<ScriptFile[]> {
  const resp = await api.get<ScriptFile[]>('/api/scripts')
  return resp.data
}

export async function fetchScriptTree(): Promise<FileTreeItem[]> {
  const resp = await api.get<FileTreeItem[]>('/api/scripts/tree')
  return resp.data
}

function scriptPathUrl(path: string): string {
  return path.split('/').map(part => encodeURIComponent(part)).join('/')
}

export async function createFolder(path: string): Promise<FileTreeItem> {
  const resp = await api.post<FileTreeItem>('/api/scripts/folder', { path })
  return resp.data
}

export async function deleteFolder(path: string): Promise<void> {
  await api.delete(`/api/scripts/folder/${scriptPathUrl(path)}`)
}

export async function fetchScript(path: string): Promise<ScriptContent> {
  const resp = await api.get<ScriptContent>(`/api/scripts/${scriptPathUrl(path)}`)
  return resp.data
}

export async function createScript(name: string, content = '', platform?: string | null): Promise<ScriptFile> {
  const payload: Record<string, string> = { name, content }
  if (platform) payload.platform = platform
  const resp = await api.post<ScriptFile>('/api/scripts', payload)
  return resp.data
}

export async function saveScript(path: string, content: string): Promise<ScriptFile> {
  const resp = await api.put<ScriptFile>(`/api/scripts/${scriptPathUrl(path)}`, { content })
  return resp.data
}

export async function deleteScript(path: string): Promise<void> {
  await api.delete(`/api/scripts/${scriptPathUrl(path)}`)
}

export async function runScript(
  path: string,
  deviceUdid: string,
  options: { platform?: string; wdaUrl?: string | null } = {},
): Promise<ScriptRunResult> {
  const params = new URLSearchParams({ path, device_udid: deviceUdid })
  if (options.platform) params.set('platform', options.platform)
  if (options.wdaUrl) params.set('wda_url', options.wdaUrl)
  try {
    const resp = await api.post<ScriptRunResult>(`/api/scripts/run?${params.toString()}`)
    return resp.data
  } catch (error) {
    if (!isMethodNotAllowed(error)) throw error
    const legacyResp = await api.post<ScriptRunResult>(`/api/scripts/${scriptPathUrl(path)}/run?${legacyScriptRunParams(deviceUdid, options).toString()}`)
    return legacyResp.data
  }
}

export async function runScriptStream(
  path: string,
  deviceUdid: string,
  options: { platform?: string; wdaUrl?: string | null; pythonEnv?: string } = {},
): Promise<ScriptRunStreamStart> {
  const params = new URLSearchParams({ path, device_udid: deviceUdid })
  if (options.platform) params.set('platform', options.platform)
  if (options.wdaUrl) params.set('wda_url', options.wdaUrl)
  if (options.pythonEnv) params.set('python_env', options.pythonEnv)
  try {
    const resp = await api.post<ScriptRunStreamStart>(`/api/scripts/run-stream?${params.toString()}`)
    return resp.data
  } catch (error) {
    if (!isMethodNotAllowed(error)) throw error
    const legacyResp = await api.post<ScriptRunStreamStart>(`/api/scripts/${scriptPathUrl(path)}/run-stream?${legacyScriptRunParams(deviceUdid, options).toString()}`)
    return legacyResp.data
  }
}

export async function runPcScriptStream(
  path: string,
  options: { session?: string; pythonEnv?: string } = {},
): Promise<ScriptRunStreamStart> {
  const params = new URLSearchParams({ path })
  if (options.session) params.set('session', options.session)
  if (options.pythonEnv) params.set('python_env', options.pythonEnv)
  try {
    const resp = await api.post<ScriptRunStreamStart>(`/api/scripts/run-pc-stream?${params.toString()}`)
    return resp.data
  } catch (error) {
    if (!isMethodNotAllowed(error)) throw error
    const legacyParams = new URLSearchParams()
    if (options.session) legacyParams.set('session', options.session)
    if (options.pythonEnv) legacyParams.set('python_env', options.pythonEnv)
    const legacyResp = await api.post<ScriptRunStreamStart>(`/api/scripts/${scriptPathUrl(path)}/run-pc-stream?${legacyParams.toString()}`)
    return legacyResp.data
  }
}

function legacyScriptRunParams(
  deviceUdid: string,
  options: { platform?: string; wdaUrl?: string | null; pythonEnv?: string } = {},
): URLSearchParams {
  const params = new URLSearchParams({ device_udid: deviceUdid })
  if (options.platform) params.set('platform', options.platform)
  if (options.wdaUrl) params.set('wda_url', options.wdaUrl)
  if (options.pythonEnv) params.set('python_env', options.pythonEnv)
  return params
}

function isMethodNotAllowed(error: unknown): boolean {
  return axios.isAxiosError(error) && error.response?.status === 405
}

export async function fetchPythonEnvs(): Promise<PythonEnvsResponse> {
  const resp = await api.get<PythonEnvsResponse>('/api/scripts/python-envs')
  return resp.data
}

export async function cancelScriptRun(runId: string): Promise<void> {
  await api.post(`/api/scripts/run/${runId}/cancel`)
}

export function getScriptOutputWebSocketUrl(runId: string): string {
  const baseUrl = new URL(apiBaseUrl)
  baseUrl.protocol = baseUrl.protocol === 'https:' ? 'wss:' : 'ws:'
  baseUrl.pathname = `/api/scripts/output/${runId}`
  return baseUrl.toString()
}

// ── User Input Requests ──────────────────────────────────────────────────────

export interface UserInputRequest {
  id: string
  prompt: string
  input_type: string
  timeout: number
  created_at: number
}

export async function fetchPendingInputRequests(): Promise<UserInputRequest[]> {
  const resp = await api.get<UserInputRequest[]>('/api/scripts/input/pending')
  return resp.data
}

export async function respondToInputRequest(requestId: string, value: string): Promise<void> {
  await api.post(`/api/scripts/input/${requestId}/respond`, { value })
}

export async function cancelInputRequest(requestId: string): Promise<void> {
  await api.post(`/api/scripts/input/${requestId}/cancel`)
}

// ── PC AutoExecute ───────────────────────────────────────────────────────────

export interface PCBrowserSessionResponse {
  session_id: string
  url: string
  title: string
}

export interface PCBrowserElement {
  ref: string
  tag: string
  text?: string | null
  attrs: Record<string, string>
  bounds?: {
    left: number
    top: number
    right: number
    bottom: number
    width: number
    height: number
  } | null
}

export interface PCBrowserLogEntry {
  timestamp: string
  session: string
  command: string[]
  returncode: number
  stdout: string
  stderr: string
  ok: boolean
}

export interface PCAgentAssertionResult {
  type: 'assert_text' | 'assert_url' | string
  passed: boolean
  expected?: string
  actual?: string
}

export interface PCAgentActionResult {
  assertion?: PCAgentAssertionResult
  eval_result?: string
  [key: string]: unknown
}

export interface PCAgentEvent {
  event: 'start' | 'log' | 'step' | 'need_user' | 'error' | 'result' | string
  type?: string
  phase?: string
  timestamp?: string
  message?: string
  run_id?: string
  step?: number
  session?: string
  task?: string
  action?: string
  decision?: Record<string, unknown>
  screenshot_path?: string
  screenshot_url?: string
  run_result?: 'passed' | 'failed' | string
  action_result?: PCAgentActionResult
  [key: string]: unknown
}

export interface PCAgentRunPayload {
  task: string
  session?: string | null
  max_steps?: number
  provider?: string
  model?: string | null
}

export interface PCAgentRunRecord {
  id: number
  run_id: string
  session: string
  task: string
  max_steps: number
  run_result: string
  result_note: string
  action_trace: PCAgentEvent[]
  steps_completed: number
  duration_ms: number | null
  started_at: string
  ended_at: string | null
  log_url: string | null
  report_url: string | null
}

export async function fetchPCAgentRuns(page = 1, pageSize = 20): Promise<{ items: PCAgentRunRecord[]; total: number }> {
  const response = await api.get<{ items: PCAgentRunRecord[]; total: number }>('/api/pc-browser/agent/runs', {
    params: { page, page_size: pageSize },
  })
  return response.data
}

export async function deletePCAgentRun(runId: string | number): Promise<void> {
  await api.delete(`/api/pc-browser/agent/runs/${encodeURIComponent(String(runId))}`)
}

export interface PCAgentProviderPreset {
  id: string
  name: string
  provider_type: string
  base_url: string
  default_model: string
  api_key_label: string
  note: string
}

export interface PCAgentModelConfig {
  enabled: boolean
  provider: string
  base_url: string
  model: string
  api_key_masked: string
  timeout_seconds: number
  temperature: number
  max_tokens: number
  configured: boolean
  presets?: PCAgentProviderPreset[]
}

export interface PCAgentModelConfigUpdate {
  enabled: boolean
  provider: string
  base_url: string
  model: string
  api_key?: string | null
  timeout_seconds: number
  temperature: number
  max_tokens: number
}

export interface LeyoujiaAuthStatus {
  env: string
  label: string
  login_url: string
  target_url: string
  state_exists: boolean
  state_path: string
}

export async function openPCBrowser(
  url: string,
  options: { session?: string; headed?: boolean } = {},
): Promise<PCBrowserSessionResponse> {
  const response = await api.post<PCBrowserSessionResponse>('/api/pc-browser/open', {
    url,
    session: options.session ?? 'pc-autoexecute',
    headed: options.headed ?? false,
  })
  return response.data
}

export async function closePCBrowser(session = 'pc-autoexecute'): Promise<void> {
  await api.post('/api/pc-browser/close', { session })
}

export async function fetchPCBrowserSnapshot(session = 'pc-autoexecute', includeBounds = false): Promise<PCBrowserElement[]> {
  const response = await api.get<{ elements: PCBrowserElement[] }>('/api/pc-browser/snapshot', { params: { session, include_bounds: includeBounds } })
  return response.data.elements
}

export async function screenshotPCBrowser(session = 'pc-autoexecute'): Promise<{ path: string; url: string }> {
  const response = await api.post<{ path: string; url: string }>('/api/pc-browser/screenshot', { session })
  return response.data
}

export async function clickPCBrowserElement(session: string, elementRef: string): Promise<void> {
  await api.post('/api/pc-browser/click', { session, element_ref: elementRef })
}

export async function fillPCBrowserElement(session: string, elementRef: string, text: string): Promise<void> {
  await api.post('/api/pc-browser/fill', { session, element_ref: elementRef, text })
}

export async function typePCBrowserText(session: string, elementRef: string, text: string): Promise<void> {
  await api.post('/api/pc-browser/type', { session, element_ref: elementRef, text })
}

export async function pressPCBrowserKey(session: string, key: string): Promise<void> {
  await api.post('/api/pc-browser/press', { session, key })
}

export async function hoverPCBrowserElement(session: string, elementRef: string): Promise<void> {
  await api.post('/api/pc-browser/hover', { session, element_ref: elementRef })
}

export async function scrollPCBrowser(session: string, direction: string, amount: number): Promise<void> {
  await api.post('/api/pc-browser/scroll', { session, direction, amount })
}

export async function selectPCBrowserOption(session: string, elementRef: string, value: string): Promise<void> {
  await api.post('/api/pc-browser/select', { session, element_ref: elementRef, value })
}

export async function checkPCBrowserElement(session: string, elementRef: string): Promise<void> {
  await api.post('/api/pc-browser/check', { session, element_ref: elementRef })
}

export async function uncheckPCBrowserElement(session: string, elementRef: string): Promise<void> {
  await api.post('/api/pc-browser/uncheck', { session, element_ref: elementRef })
}

export async function findAndClickPCBrowser(session: string, text: string, exact = false): Promise<void> {
  await api.post('/api/pc-browser/find/click', { session, text, exact })
}

export async function findAndFillPCBrowser(session: string, label: string, text: string): Promise<void> {
  await api.post('/api/pc-browser/find/fill', { session, label, text })
}

export async function getPCBrowserUrl(session = 'pc-autoexecute'): Promise<string> {
  const response = await api.get<{ url: string }>('/api/pc-browser/url', { params: { session } })
  return response.data.url
}

export async function getPCBrowserTitle(session = 'pc-autoexecute'): Promise<string> {
  const response = await api.get<{ title: string }>('/api/pc-browser/title', { params: { session } })
  return response.data.title
}

export async function fetchPCBrowserLogs(session = 'pc-autoexecute'): Promise<PCBrowserLogEntry[]> {
  const response = await api.get<{ logs: PCBrowserLogEntry[] }>('/api/pc-browser/logs', { params: { session } })
  return response.data.logs
}

export async function fetchPCAgentModelConfig(): Promise<PCAgentModelConfig> {
  const response = await api.get<PCAgentModelConfig>('/api/pc-browser/agent/model/config')
  return response.data
}

export async function updatePCAgentModelConfig(payload: PCAgentModelConfigUpdate): Promise<PCAgentModelConfig> {
  const response = await api.put<PCAgentModelConfig>('/api/pc-browser/agent/model/config', payload)
  return response.data
}

export async function fetchPCAgentModelPresets(): Promise<PCAgentProviderPreset[]> {
  const response = await api.get<{ presets: PCAgentProviderPreset[] }>('/api/pc-browser/agent/model/presets')
  return response.data.presets
}

export async function testPCAgentModel(
  task = '测试 PC Agent 模型连接',
  config?: PCAgentModelConfigUpdate,
): Promise<{ ok: boolean; decision?: Record<string, unknown>; error?: string }> {
  const response = await api.post<{ ok: boolean; decision?: Record<string, unknown>; error?: string }>(
    '/api/pc-browser/agent/model/test',
    { task, config },
  )
  return response.data
}

export async function fetchLeyoujiaAuthStatus(env: 'test' | 'prod' = 'test'): Promise<LeyoujiaAuthStatus> {
  const response = await api.get<LeyoujiaAuthStatus>('/api/pc-browser/auth/leyoujia/status', { params: { env } })
  return response.data
}

export async function openLeyoujiaLogin(session = 'pc-autoexecute', env: 'test' | 'prod' = 'test'): Promise<PCBrowserSessionResponse> {
  const response = await api.post<PCBrowserSessionResponse>('/api/pc-browser/auth/leyoujia/open-login', { session, env })
  return response.data
}

export async function saveLeyoujiaAuthState(session = 'pc-autoexecute', env: 'test' | 'prod' = 'test'): Promise<LeyoujiaAuthStatus & { status: string }> {
  const response = await api.post<LeyoujiaAuthStatus & { status: string }>('/api/pc-browser/auth/leyoujia/save', { session, env })
  return response.data
}

export async function loadLeyoujiaAuthState(session = 'pc-autoexecute', env: 'test' | 'prod' = 'test'): Promise<LeyoujiaAuthStatus & { status: string }> {
  const response = await api.post<LeyoujiaAuthStatus & { status: string }>('/api/pc-browser/auth/leyoujia/load', { session, env })
  return response.data
}

export async function resumeAgentRun(runId: string): Promise<{ status: string }> {
  const res = await fetch(`${apiBaseUrl}/api/pc-browser/agent/run/${runId}/resume`, {
    method: 'POST',
  })
  if (!res.ok) throw new Error('恢复执行失败')
  return res.json()
}

export async function cancelAgentRun(runId: string): Promise<{ status: string }> {
  const res = await fetch(`${apiBaseUrl}/api/pc-browser/agent/run/${runId}/cancel`, {
    method: 'POST',
  })
  if (!res.ok) throw new Error('取消执行失败')
  return res.json()
}

export async function runPCAgentStream(
  payload: PCAgentRunPayload,
  onEvent: (event: PCAgentEvent) => void,
  signal?: AbortSignal,
): Promise<PCAgentEvent | null> {
  const response = await fetch(`${apiBaseUrl}/api/pc-browser/agent/run/stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
    signal,
  })
  if (!response.ok) {
    const message = await response.text()
    throw new Error(message || `PC Agent 执行失败：${response.status}`)
  }
  if (!response.body) {
    throw new Error('浏览器不支持读取流式响应')
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  let finalEvent: PCAgentEvent | null = null

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() ?? ''
    for (const line of lines) {
      const value = line.trim()
      if (!value) continue
      let event: PCAgentEvent
      try {
        event = JSON.parse(value) as PCAgentEvent
      } catch {
        event = {
          event: 'log',
          phase: 'execution',
          message: value,
        }
      }
      onEvent(event)
      finalEvent = event
    }
  }

  return finalEvent
}

export interface ApiTestSuite {
  id: number
  name: string
  base_url: string
  headers?: Record<string, string>
  auth_type?: string | null
  auth_config?: Record<string, unknown> | null
  cases?: ApiTestCase[]
  created_at?: string
  updated_at?: string
}

export interface ApiTestCase {
  id: number
  suite_id: number
  sequence: number
  name: string
  method: string
  path: string
  headers?: Record<string, string>
  params?: Record<string, unknown>
  body?: Record<string, unknown> | null
  expected_status: number
  expected_body_contains?: string | null
  expected_schema?: Record<string, unknown> | null
  extract_vars?: Record<string, string> | null
  tags?: string | null
  priority?: string | null
  run_count: number
  latest_result: string
  latest_result_note: string
  executions?: ApiTestExecution[]
}

export interface ApiTestExecution {
  id: number
  suite_id: number
  case_id: number
  run_index: number
  request_url: string
  request_method: string
  request_headers?: Record<string, unknown>
  request_body?: Record<string, unknown> | null
  response_status: number | null
  response_headers: Record<string, unknown> | null
  response_body: Record<string, unknown> | null
  response_body_text: string | null
  response_time_ms: number | null
  run_result: string
  result_note: string
  assertion_detail?: Record<string, unknown> | null
  started_at: string
  ended_at: string | null
  duration_ms: number | null
}

export interface ApiTestSuiteRunResponse {
  suite_id: number
  total_cases: number
  executions: ApiTestExecution[]
}

export async function fetchApiTestSuites(): Promise<ApiTestSuite[]> {
  const response = await api.get<ApiTestSuite[]>('/api/api-tests/suites')
  return response.data
}

export async function createApiTestSuite(payload: {
  name: string
  base_url?: string
  headers?: Record<string, string>
  auth_type?: string | null
  auth_config?: Record<string, unknown> | null
}): Promise<ApiTestSuite> {
  const response = await api.post<ApiTestSuite>('/api/api-tests/suites', payload)
  return response.data
}

export async function fetchApiTestSuite(suiteId: number): Promise<ApiTestSuite> {
  const response = await api.get<ApiTestSuite>(`/api/api-tests/suites/${suiteId}`)
  return response.data
}

export async function updateApiTestSuite(suiteId: number, payload: {
  name: string
  base_url?: string
  headers?: Record<string, string>
  auth_type?: string | null
  auth_config?: Record<string, unknown> | null
}): Promise<ApiTestSuite> {
  const response = await api.put<ApiTestSuite>(`/api/api-tests/suites/${suiteId}`, payload)
  return response.data
}

export async function deleteApiTestSuite(suiteId: number): Promise<void> {
  await api.delete(`/api/api-tests/suites/${suiteId}`)
}

export async function createApiTestCase(
  suiteId: number,
  payload: {
    name: string
    method?: string
    path?: string
    headers?: Record<string, string>
    params?: Record<string, unknown>
    body?: Record<string, unknown> | null
    expected_status?: number
    expected_body_contains?: string | null
    expected_schema?: Record<string, unknown> | null
    extract_vars?: Record<string, string> | null
    tags?: string | null
    priority?: string | null
  },
): Promise<ApiTestCase> {
  const response = await api.post<ApiTestCase>(`/api/api-tests/suites/${suiteId}/cases`, payload)
  return response.data
}

export async function updateApiTestCase(
  caseId: number,
  payload: {
    name: string
    method?: string
    path?: string
    headers?: Record<string, string>
    params?: Record<string, unknown>
    body?: Record<string, unknown> | null
    expected_status?: number
    expected_body_contains?: string | null
    expected_schema?: Record<string, unknown> | null
    extract_vars?: Record<string, string> | null
    tags?: string | null
    priority?: string | null
  },
): Promise<ApiTestCase> {
  const response = await api.put<ApiTestCase>(`/api/api-tests/cases/${caseId}`, payload)
  return response.data
}

export async function deleteApiTestCase(caseId: number): Promise<void> {
  await api.delete(`/api/api-tests/cases/${caseId}`)
}

export async function runApiTestCase(caseId: number): Promise<ApiTestExecution> {
  const response = await api.post<ApiTestExecution>(`/api/api-tests/cases/${caseId}/run`)
  return response.data
}

export async function runApiTestSuite(suiteId: number): Promise<ApiTestSuiteRunResponse> {
  const response = await api.post<ApiTestSuiteRunResponse>(`/api/api-tests/suites/${suiteId}/run`)
  return response.data
}

// ── Automation Engine V2 ──────────────────────────────────────────────────────

export interface ImageCompareResponse {
  matched: boolean
  score: number
  location: number[] | null
  threshold: number
}

export interface ImageCaptureTemplateResponse {
  template_path: string
  template_name: string
}

export interface AutoGLMPlanResponse {
  case_id: number
  target_app: string
  platform: string
  launch_app_id: string
  preconditions: string[]
  checkpoints: Array<{
    id: string
    goal: string
    instructions: string[]
    success_signals: string[]
    failure_signals: string[]
    takeover_signals: string[]
    allowed_actions: string[]
    max_steps: number
  }>
  final_expectations: string[]
}

export interface AutoGLMValidateCheckpointResponse {
  passed: boolean
  failed: boolean
  message: string
}

export async function imageCompare(
  udid: string,
  platform: string,
  imagePath: string,
  threshold = 0.9,
  wdaUrl?: string | null,
): Promise<ImageCompareResponse> {
  const params = new URLSearchParams({ udid, platform })
  if (wdaUrl) params.set('wda_url', wdaUrl)
  const response = await api.post<ImageCompareResponse>(
    `/api/automation/image/compare?${params.toString()}`,
    { image_path: imagePath, threshold },
  )
  return response.data
}

export async function captureTemplate(
  udid: string,
  platform: string,
  name?: string | null,
  wdaUrl?: string | null,
): Promise<ImageCaptureTemplateResponse> {
  const params = new URLSearchParams({ udid, platform })
  if (name) params.set('name', name)
  if (wdaUrl) params.set('wda_url', wdaUrl)
  const response = await api.post<ImageCaptureTemplateResponse>(
    `/api/automation/image/capture-template?${params.toString()}`,
  )
  return response.data
}

export async function buildAutoGLMPlan(payload: {
  case_id: number
  target_app: string
  platform: string
  launch_app_id?: string
  preconditions?: string[]
  steps?: string[]
  expected_result?: string
}): Promise<AutoGLMPlanResponse> {
  const response = await api.post<AutoGLMPlanResponse>('/api/automation/autoglm/plan', payload)
  return response.data
}

export async function validateAutoGLMCheckpoint(
  udid: string,
  platform: string,
  checkpoint: {
    id: string
    goal: string
    success_signals?: string[]
    failure_signals?: string[]
    max_steps?: number
  },
  wdaUrl?: string | null,
): Promise<AutoGLMValidateCheckpointResponse> {
  const params = new URLSearchParams({ udid, platform })
  if (wdaUrl) params.set('wda_url', wdaUrl)
  const response = await api.post<AutoGLMValidateCheckpointResponse>(
    `/api/automation/autoglm/validate-checkpoint?${params.toString()}`,
    checkpoint,
  )
  return response.data
}
