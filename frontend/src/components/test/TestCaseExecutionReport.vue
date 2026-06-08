<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import {
  Download,
  Picture,
  Warning,
  CircleCheck,
  CircleClose,
  Timer,
  Cellphone,
  CopyDocument,
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import {
  fetchExecutionDetailReport,
  exportExecutionReport,
  getAssetUrl,
  type ExecutionDetailReport,
  type TestCaseRunStreamEvent,
} from '../../api'
import CaseStepLog from './CaseStepLog.vue'

const props = defineProps<{
  executionId: number | null
  visible: boolean
}>()

const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
  (e: 'close'): void
}>()

const report = ref<ExecutionDetailReport | null>(null)
const loading = ref(false)
const exporting = ref(false)
const activeTab = ref('summary')
const currentScreenshotIndex = ref(0)

const errorCategoryColors: Record<string, string> = {
  api_error: 'danger',
  device_error: 'warning',
  element_not_found: 'info',
  timeout: 'warning',
  app_error: 'danger',
  assertion_failed: 'danger',
  assertion_uncertain: 'warning',
  no_device: 'warning',
  max_steps: 'warning',
  action_parse_error: 'danger',
  app_not_found: 'danger',
  agent_error: 'danger',
  execution_failed: 'danger',
  unknown: 'info',
}

const errorCategoryLabels: Record<string, string> = {
  api_error: 'API 错误',
  device_error: '设备错误',
  element_not_found: '元素未找到',
  timeout: '执行超时',
  app_error: '应用错误',
  assertion_failed: '断言失败',
  assertion_uncertain: '断言不确定',
  no_device: '未选择设备',
  max_steps: '达到最大步数',
  action_parse_error: '动作解析失败',
  app_not_found: '应用未找到',
  agent_error: 'Agent 异常',
  execution_failed: '执行失败',
  unknown: '未知错误',
}

const resultColor = computed(() => {
  if (!report.value) return 'info'
  return report.value.result === 'passed' ? 'success' : 'danger'
})

const resultIcon = computed(() => {
  if (!report.value) return CircleClose
  return report.value.result === 'passed' ? CircleCheck : CircleClose
})

const errorCategoryLabel = computed(() => {
  if (!report.value?.error_category) return ''
  return errorCategoryLabels[report.value.error_category] || report.value.error_category
})

const errorCategoryColor = computed(() => {
  if (!report.value?.error_category) return 'info'
  return errorCategoryColors[report.value.error_category] || 'info'
})

const assertionColor = computed(() => {
  const verdict = report.value?.assertion_result?.verdict
  if (verdict === 'passed') return 'success'
  if (verdict === 'failed') return 'danger'
  if (verdict === 'uncertain') return 'warning'
  return 'info'
})

const assertionLabel = computed(() => {
  const verdict = report.value?.assertion_result?.verdict
  if (verdict === 'passed') return '通过'
  if (verdict === 'failed') return '失败'
  if (verdict === 'uncertain') return '不确定'
  return verdict || '未断言'
})

/** Convert ExecutionDetailReport action_summary to log events for CaseStepLog */
const stepLogEvents = computed<TestCaseRunStreamEvent[]>(() => {
  if (!report.value) return []
  const events: TestCaseRunStreamEvent[] = []

  // Add header event with trace_id
  events.push({
    event: 'log',
    type: 'case_task_plan',
    phase: 'device_check',
    timestamp: report.value.started_at ?? undefined,
    message: `设备: ${report.value.device_udid || '未知'}`,
    trace_id: report.value.trace_id ?? undefined,
  })

  for (const action of report.value.action_summary) {
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

  events.push({
    event: 'result',
    type: 'result',
    phase: 'report',
    message: report.value.result_note || report.value.result || '',
    run_result: report.value.result as TestCaseRunStreamEvent['run_result'],
    duration_ms: report.value.duration_ms,
    trace_id: report.value.trace_id ?? undefined,
  })

  return events
})

async function loadReport() {
  if (!props.executionId) return

  loading.value = true
  try {
    report.value = await fetchExecutionDetailReport(props.executionId)
    currentScreenshotIndex.value = 0
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '加载报告失败')
  } finally {
    loading.value = false
  }
}

function close() {
  emit('update:visible', false)
  emit('close')
}

async function exportCurrentReport(format: 'json' | 'html') {
  if (!props.executionId) return

  exporting.value = true
  try {
    const result = await exportExecutionReport(props.executionId, format)
    const content = format === 'html'
      ? result.html || ''
      : JSON.stringify(result.report || report.value, null, 2)
    const blob = new Blob([content], {
      type: format === 'html' ? 'text/html;charset=utf-8' : 'application/json;charset=utf-8',
    })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = result.filename
    link.click()
    URL.revokeObjectURL(url)
    ElMessage.success('单用例报告已导出')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '导出报告失败')
  } finally {
    exporting.value = false
  }
}

function formatDuration(ms: number | null): string {
  if (!ms) return '-'
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(2)}s`
}

function formatTime(isoString: string | null): string {
  if (!isoString) return '-'
  return new Date(isoString).toLocaleString()
}

async function copyTraceId() {
  if (!report.value?.trace_id) return
  try {
    await window.navigator.clipboard.writeText(report.value.trace_id)
    ElMessage.success('Trace ID 已复制')
  } catch {
    ElMessage.warning('复制失败')
  }
}

watch(() => props.executionId, (newId) => {
  if (newId && props.visible) {
    loadReport()
  }
})

watch(() => props.visible, (visible) => {
  if (visible && props.executionId) {
    loadReport()
  }
})
</script>

<template>
  <el-drawer
    :model-value="visible"
    direction="rtl"
    size="600px"
    @close="close"
  >
    <template #header>
      <div class="drawer-header">
        <span>执行报告详情</span>
        <div v-if="report" class="drawer-actions">
          <el-button :icon="Download" :loading="exporting" size="small" @click.stop="exportCurrentReport('html')">
            HTML
          </el-button>
          <el-button :loading="exporting" size="small" @click.stop="exportCurrentReport('json')">
            JSON
          </el-button>
        </div>
        <el-tag v-if="report" :type="resultColor" effect="light">
          {{ report.result }}
        </el-tag>
      </div>
    </template>

    <div v-loading="loading" class="report-content">
      <div v-if="!report && !loading" class="empty-state">
        <el-icon :size="48"><Warning /></el-icon>
        <p>选择一个执行记录查看详情</p>
      </div>

      <template v-else-if="report">
        <!-- Summary Section -->
        <div class="report-section">
          <div class="summary-header">
            <h3>{{ report.case_name }}</h3>
            <el-tag v-if="report.error_category" :type="errorCategoryColor" effect="plain">
              {{ errorCategoryLabel }}
            </el-tag>
          </div>

          <div class="summary-grid">
            <div class="summary-item">
              <el-icon><Timer /></el-icon>
              <span class="label">执行时间</span>
              <span class="value">{{ formatDuration(report.duration_ms) }}</span>
            </div>
            <div class="summary-item">
              <el-icon><Cellphone /></el-icon>
              <span class="label">设备</span>
              <span class="value">{{ report.device_udid || '-' }}</span>
            </div>
            <div class="summary-item">
              <span class="label">开始</span>
              <span class="value">{{ formatTime(report.started_at) }}</span>
            </div>
            <div class="summary-item">
              <span class="label">结束</span>
              <span class="value">{{ formatTime(report.ended_at) }}</span>
            </div>
          </div>

          <div v-if="report.trace_id" class="trace-id-row">
            <span class="label">Trace ID</span>
            <code>{{ report.trace_id }}</code>
            <el-button
              :icon="CopyDocument"
              size="small"
              text
              @click="copyTraceId"
            />
          </div>

          <div v-if="report.result_note" class="result-note">
            <strong>结果说明：</strong>
            <p>{{ report.result_note }}</p>
          </div>

          <div v-if="report.assertion_result" class="assertion-box">
            <div class="assertion-title">
              <strong>断言结论</strong>
              <el-tag :type="assertionColor" size="small" effect="light">
                {{ assertionLabel }}
              </el-tag>
              <span v-if="typeof report.assertion_result.confidence === 'number'" class="assertion-confidence">
                置信度 {{ Math.round(report.assertion_result.confidence * 100) }}%
              </span>
            </div>
            <p v-if="report.assertion_result.reason" class="assertion-reason">
              {{ report.assertion_result.reason }}
            </p>
            <div v-if="report.assertion_result.evidence?.length" class="assertion-list">
              <span>证据</span>
              <ul>
                <li v-for="item in report.assertion_result.evidence" :key="item">{{ item }}</li>
              </ul>
            </div>
            <div v-if="report.assertion_result.failed_expectations?.length" class="assertion-list failed">
              <span>未满足项</span>
              <ul>
                <li v-for="item in report.assertion_result.failed_expectations" :key="item">{{ item }}</li>
              </ul>
            </div>
          </div>
        </div>

        <!-- Tabs -->
        <el-tabs v-model="activeTab" class="report-tabs">
          <el-tab-pane label="截图" name="screenshots">
            <div v-if="report.screenshots.length === 0" class="tab-empty">
              暂无截图
            </div>
            <div v-else class="screenshots-container">
              <div class="screenshot-main">
                <img
                  v-if="report.screenshots[currentScreenshotIndex]?.url"
                  :src="getAssetUrl(report.screenshots[currentScreenshotIndex].url || '')"
                  alt="Screenshot"
                />
                <div v-else class="no-screenshot">截图不可用</div>
              </div>
              <div class="screenshot-info">
                <span>步骤 {{ report.screenshots[currentScreenshotIndex]?.step }}</span>
                <span v-if="report.screenshots[currentScreenshotIndex]?.current_app">
                  {{ report.screenshots[currentScreenshotIndex].current_app }}
                </span>
              </div>
              <div v-if="report.screenshots.length > 1" class="screenshot-thumbnails">
                <div
                  v-for="(screenshot, index) in report.screenshots"
                  :key="index"
                  class="thumbnail"
                  :class="{ active: index === currentScreenshotIndex }"
                  @click="currentScreenshotIndex = index"
                >
                  <el-icon><Picture /></el-icon>
                  <span>{{ screenshot.step }}</span>
                </div>
              </div>
            </div>
          </el-tab-pane>

          <el-tab-pane label="执行步骤" name="actions">
            <CaseStepLog
              :events="stepLogEvents"
              @preview="(url: string) => { /* handled by screenshots tab */ }"
            />
          </el-tab-pane>

          <el-tab-pane label="错误详情" name="errors">
            <div v-if="report.error_details.length === 0" class="tab-empty">
              <el-icon><CircleCheck /></el-icon>
              <span>无错误</span>
            </div>
            <div v-else class="errors-list">
              <el-alert
                v-for="(error, index) in report.error_details"
                :key="index"
                type="error"
                :closable="false"
                show-icon
                class="error-alert"
              >
                <template #title>
                  <span v-if="error.category" class="error-category">{{ error.category }}</span>
                  <span v-if="error.exception_type" class="error-type">{{ error.exception_type }}</span>
                </template>
                <pre class="error-message">{{ error.error || error.details || JSON.stringify(error, null, 2) }}</pre>
              </el-alert>
            </div>
          </el-tab-pane>

          <el-tab-pane label="完整日志" name="trace">
            <div class="trace-container">
              <pre class="trace-content">{{ JSON.stringify(report.full_trace, null, 2) }}</pre>
            </div>
          </el-tab-pane>
        </el-tabs>
      </template>
    </div>
  </el-drawer>
</template>

<style scoped>
.drawer-header {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
}

.drawer-header span {
  font-size: 16px;
  font-weight: 600;
}

.drawer-actions {
  display: flex;
  gap: 8px;
  margin-left: auto;
}

.report-content {
  height: 100%;
  overflow-y: auto;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 200px;
  color: var(--el-text-color-secondary);
  gap: 12px;
}

.report-section {
  padding: 16px;
  border-bottom: 1px solid var(--el-border-color);
}

.summary-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}

.summary-header h3 {
  margin: 0;
  font-size: 18px;
  color: var(--el-text-color-primary);
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
}

.summary-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 12px;
  background: var(--el-fill-color-light);
  border-radius: 6px;
}

.summary-item .label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.summary-item .value {
  font-size: 14px;
  color: var(--el-text-color-primary);
  font-weight: 500;
}

.trace-id-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 12px;
  padding: 8px 12px;
  background: var(--el-fill-color-light);
  border-radius: 6px;
  font-size: 12px;
}

.trace-id-row .label {
  color: var(--el-text-color-secondary);
  font-weight: 500;
  white-space: nowrap;
}

.trace-id-row code {
  color: var(--el-color-primary);
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 12px;
  background: var(--el-fill-color);
  padding: 2px 6px;
  border-radius: 3px;
}

.result-note {
  margin-top: 16px;
  padding: 12px;
  background: var(--el-color-warning-light-9);
  border-radius: 6px;
}

.result-note strong {
  display: block;
  margin-bottom: 8px;
  color: var(--el-text-color-primary);
}

.result-note p {
  margin: 0;
  font-size: 13px;
  line-height: 1.6;
  color: var(--el-text-color-regular);
}

.assertion-box {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 12px;
  padding: 12px;
  border: 1px solid var(--el-border-color);
  border-radius: 6px;
  background: var(--el-fill-color-extra-light);
}

.assertion-title {
  display: flex;
  align-items: center;
  gap: 8px;
}

.assertion-confidence {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.assertion-reason {
  margin: 0;
  color: var(--el-text-color-regular);
  font-size: 13px;
  line-height: 1.5;
}

.assertion-list {
  color: var(--el-text-color-regular);
  font-size: 12px;
}

.assertion-list span {
  color: var(--el-text-color-secondary);
  font-weight: 600;
}

.assertion-list ul {
  margin: 6px 0 0;
  padding-left: 18px;
}

.assertion-list.failed {
  color: var(--el-color-danger);
}

.report-tabs {
  padding: 16px;
}

.report-tabs :deep(.el-tabs__content) {
  max-height: calc(100vh - 280px);
  overflow-y: auto;
}

.tab-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 150px;
  color: var(--el-text-color-secondary);
  gap: 8px;
}

.screenshots-container {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.screenshot-main {
  width: 100%;
  aspect-ratio: 9/16;
  max-height: 400px;
  background: var(--el-fill-color);
  border-radius: 8px;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
}

.screenshot-main img {
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
}

.no-screenshot {
  color: var(--el-text-color-secondary);
}

.screenshot-info {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.screenshot-thumbnails {
  display: flex;
  gap: 8px;
  overflow-x: auto;
  padding: 8px 0;
}

.thumbnail {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: 8px 12px;
  background: var(--el-fill-color);
  border-radius: 6px;
  cursor: pointer;
  font-size: 12px;
  border: 2px solid transparent;
}

.thumbnail:hover {
  background: var(--el-fill-color-dark);
}

.thumbnail.active {
  border-color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
}

.actions-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.action-item {
  padding: 12px;
  background: var(--el-fill-color-light);
  border-radius: 6px;
  border-left: 3px solid var(--el-color-success);
}

.action-item.failed {
  border-left-color: var(--el-color-danger);
  background: var(--el-color-danger-light-9);
}

.action-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.action-header .success {
  color: var(--el-color-success);
}

.action-header .error {
  color: var(--el-color-danger);
}

.action-header .step {
  font-weight: 500;
  font-size: 13px;
}

.action-message {
  font-size: 12px;
  color: var(--el-text-color-regular);
  line-height: 1.5;
}

.errors-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.error-alert {
  margin: 0;
}

.error-category {
  font-weight: 500;
  margin-right: 8px;
}

.error-type {
  font-family: monospace;
  background: var(--el-color-danger-light-8);
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 12px;
}

.error-message {
  margin: 8px 0 0;
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 200px;
  overflow-y: auto;
}

.trace-container {
  background: var(--el-fill-color);
  border-radius: 6px;
  overflow: hidden;
  max-height: 60vh;
  overflow-y: auto;
}

.trace-content {
  margin: 0;
  padding: 12px;
  font-size: 11px;
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 500px;
  overflow-y: auto;
}
</style>
