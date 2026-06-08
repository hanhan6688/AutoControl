<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import {
  Refresh,
  Delete,
  Warning,
  InfoFilled,
  CircleClose,
  Cpu,
  Connection,
  Cellphone,
  Document,
} from '@element-plus/icons-vue'
import { api } from '../../api'

interface DiagnosticEntry {
  id: string
  timestamp: string
  category: string
  level: string
  source: string
  message: string
  details: Record<string, any>
  duration_ms: number | null
}

interface DiagnosticSummary {
  total_entries: number
  by_category: Record<string, number>
  by_level: Record<string, number>
  recent_errors: DiagnosticEntry[]
  execution_context: Record<string, any>
}

const summary = ref<DiagnosticSummary | null>(null)
const entries = ref<DiagnosticEntry[]>([])
const loading = ref(false)
const activeCategory = ref<string | null>(null)
const activeLevel = ref<string | null>(null)
const autoRefresh = ref(true)
const refreshInterval = ref<number | null>(null)

const categoryIcons: Record<string, any> = {
  api: Connection,
  adb: Cpu,
  websocket: Connection,
  action: Cellphone,
  error: CircleClose,
  system: InfoFilled,
}

const levelColors: Record<string, string> = {
  info: 'info',
  warning: 'warning',
  error: 'danger',
}

async function fetchSummary() {
  try {
    const res = await api.get<DiagnosticSummary>('/api/diagnostic/summary')
    summary.value = res.data
  } catch (e) {
    console.error('Failed to fetch diagnostic summary:', e)
  }
}

async function fetchEntries() {
  loading.value = true
  try {
    const params = new URLSearchParams()
    if (activeCategory.value) params.append('category', activeCategory.value)
    if (activeLevel.value) params.append('level', activeLevel.value)
    params.append('limit', '200')

    const res = await api.get<DiagnosticEntry[]>(`/api/diagnostic/entries?${params}`)
    entries.value = res.data
  } catch (e) {
    console.error('Failed to fetch diagnostic entries:', e)
  } finally {
    loading.value = false
  }
}

async function clearEntries() {
  try {
    await api.delete('/api/diagnostic/entries')
    await fetchSummary()
    await fetchEntries()
  } catch (e) {
    console.error('Failed to clear entries:', e)
  }
}

async function refresh() {
  await Promise.all([fetchSummary(), fetchEntries()])
}

function formatTime(timestamp: string): string {
  return new Date(timestamp).toLocaleTimeString()
}

function formatDetails(details: Record<string, any>): string {
  return JSON.stringify(details, null, 2)
}

function setFilter(category: string | null, level: string | null) {
  activeCategory.value = category
  activeLevel.value = level
  fetchEntries()
}

onMounted(() => {
  refresh()
  if (autoRefresh.value) {
    refreshInterval.value = window.setInterval(refresh, 5000)
  }
})

onUnmounted(() => {
  if (refreshInterval.value) {
    clearInterval(refreshInterval.value)
  }
})
</script>

<template>
  <div class="diagnostic-panel">
    <!-- Header -->
    <div class="diagnostic-header">
      <h3>诊断面板</h3>
      <div class="header-actions">
        <el-checkbox v-model="autoRefresh">自动刷新</el-checkbox>
        <el-button :icon="Refresh" size="small" @click="refresh">刷新</el-button>
        <el-button :icon="Delete" size="small" type="danger" @click="clearEntries">清空</el-button>
      </div>
    </div>

    <!-- Summary Cards -->
    <div v-if="summary" class="summary-cards">
      <el-card class="summary-card" shadow="hover">
        <div class="summary-value">{{ summary.total_entries }}</div>
        <div class="summary-label">总日志数</div>
      </el-card>
      <el-card
        class="summary-card clickable"
        :class="{ active: activeLevel === 'error' }"
        shadow="hover"
        @click="setFilter(null, activeLevel === 'error' ? null : 'error')"
      >
        <div class="summary-value error">{{ summary.by_level.error || 0 }}</div>
        <div class="summary-label">错误</div>
      </el-card>
      <el-card
        class="summary-card clickable"
        :class="{ active: activeLevel === 'warning' }"
        shadow="hover"
        @click="setFilter(null, activeLevel === 'warning' ? null : 'warning')"
      >
        <div class="summary-value warning">{{ summary.by_level.warning || 0 }}</div>
        <div class="summary-label">警告</div>
      </el-card>
      <el-card
        class="summary-card clickable"
        :class="{ active: activeCategory === 'api' }"
        shadow="hover"
        @click="setFilter(activeCategory === 'api' ? null : 'api', null)"
      >
        <div class="summary-value">{{ summary.by_category.api || 0 }}</div>
        <div class="summary-label">API调用</div>
      </el-card>
      <el-card
        class="summary-card clickable"
        :class="{ active: activeCategory === 'adb' }"
        shadow="hover"
        @click="setFilter(activeCategory === 'adb' ? null : 'adb', null)"
      >
        <div class="summary-value">{{ summary.by_category.adb || 0 }}</div>
        <div class="summary-label">ADB命令</div>
      </el-card>
    </div>

    <!-- Execution Context -->
    <div v-if="summary?.execution_context?.execution_id" class="execution-context">
      <el-tag type="info">执行中: {{ summary.execution_context.case_name }}</el-tag>
      <span class="context-time">{{ summary.execution_context.start_time }}</span>
    </div>

    <!-- Filter Tags -->
    <div v-if="activeCategory || activeLevel" class="active-filters">
      <span>筛选:</span>
      <el-tag v-if="activeCategory" closable @close="setFilter(null, activeLevel)">
        {{ activeCategory }}
      </el-tag>
      <el-tag v-if="activeLevel" :type="levelColors[activeLevel]" closable @close="setFilter(activeCategory, null)">
        {{ activeLevel }}
      </el-tag>
      <el-button size="small" text @click="setFilter(null, null)">清除筛选</el-button>
    </div>

    <!-- Entries List -->
    <div class="entries-list" v-loading="loading">
      <div
        v-for="entry in entries"
        :key="entry.id"
        class="entry-item"
        :class="`entry-${entry.level}`"
      >
        <div class="entry-header">
          <el-icon class="entry-icon" :class="`icon-${entry.category}`">
            <component :is="categoryIcons[entry.category] || Document" />
          </el-icon>
          <span class="entry-category">{{ entry.category }}</span>
          <el-tag :type="levelColors[entry.level] as any" size="small">{{ entry.level }}</el-tag>
          <span class="entry-time">{{ formatTime(entry.timestamp) }}</span>
          <span v-if="entry.duration_ms" class="entry-duration">{{ entry.duration_ms }}ms</span>
        </div>
        <div class="entry-message">{{ entry.message }}</div>
        <div v-if="Object.keys(entry.details).length > 0" class="entry-details">
          <el-collapse>
            <el-collapse-item title="详情">
              <pre>{{ formatDetails(entry.details) }}</pre>
            </el-collapse-item>
          </el-collapse>
        </div>
      </div>

      <el-empty v-if="!entries.length && !loading" description="暂无诊断日志" />
    </div>
  </div>
</template>

<style scoped>
.diagnostic-panel {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--el-bg-color);
  border-radius: 8px;
  overflow: hidden;
}

.diagnostic-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid var(--el-border-color);
}

.diagnostic-header h3 {
  margin: 0;
  font-size: 16px;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.summary-cards {
  display: flex;
  gap: 12px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--el-border-color);
  overflow-x: auto;
}

.summary-card {
  min-width: 100px;
  text-align: center;
}

.summary-card.clickable {
  cursor: pointer;
}

.summary-card.clickable:hover {
  border-color: var(--el-color-primary);
}

.summary-card.active {
  border-color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
}

.summary-value {
  font-size: 24px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.summary-value.error {
  color: var(--el-color-danger);
}

.summary-value.warning {
  color: var(--el-color-warning);
}

.summary-label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-top: 4px;
}

.execution-context {
  padding: 8px 16px;
  background: var(--el-color-primary-light-9);
  display: flex;
  align-items: center;
  gap: 12px;
}

.context-time {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.active-filters {
  padding: 8px 16px;
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.entries-list {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
}

.entry-item {
  padding: 12px;
  margin-bottom: 8px;
  border-radius: 6px;
  border: 1px solid var(--el-border-color);
  background: var(--el-bg-color);
}

.entry-item.entry-error {
  border-color: var(--el-color-danger-light-5);
  background: var(--el-color-danger-light-9);
}

.entry-item.entry-warning {
  border-color: var(--el-color-warning-light-5);
  background: var(--el-color-warning-light-9);
}

.entry-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.entry-icon {
  font-size: 16px;
}

.icon-api { color: var(--el-color-primary); }
.icon-adb { color: var(--el-color-success); }
.icon-websocket { color: var(--el-color-info); }
.icon-action { color: var(--el-color-warning); }
.icon-error { color: var(--el-color-danger); }

.entry-category {
  font-size: 12px;
  font-weight: 500;
  text-transform: uppercase;
}

.entry-time {
  margin-left: auto;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.entry-duration {
  font-size: 11px;
  color: var(--el-text-color-secondary);
  background: var(--el-fill-color);
  padding: 2px 6px;
  border-radius: 4px;
}

.entry-message {
  font-size: 13px;
  color: var(--el-text-color-primary);
  word-break: break-all;
}

.entry-details {
  margin-top: 8px;
}

.entry-details pre {
  font-size: 11px;
  background: var(--el-fill-color-light);
  padding: 8px;
  border-radius: 4px;
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
