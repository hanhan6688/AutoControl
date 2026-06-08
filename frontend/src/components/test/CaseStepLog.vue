<script setup lang="ts">
import { computed, ref, nextTick, watch } from 'vue'
import {
  ArrowDown,
  ArrowRight,
  Check,
  Close,
  Warning,
  PictureFilled,
  VideoPlay,
  Loading,
} from '@element-plus/icons-vue'
import { getAssetUrl } from '../../api'
import type { TestCaseRunStreamEvent } from '../../api'

/* ------------------------------------------------------------------ */
/*  Props & emits                                                      */
/* ------------------------------------------------------------------ */

const props = withDefaults(
  defineProps<{
    events: TestCaseRunStreamEvent[]
    showScreenshots?: boolean
    collapsible?: boolean
  }>(),
  {
    showScreenshots: true,
    collapsible: true,
  },
)

const emit = defineEmits<{
  preview: [url: string]
}>()

/* ------------------------------------------------------------------ */
/*  Constants                                                          */
/* ------------------------------------------------------------------ */

const PHASE_ORDER = ['device_check', 'precondition', 'execution', 'report'] as const

const PHASE_META: Record<string, { label: string; icon: string }> = {
  device_check: { label: '设备检测', icon: '🔍' },
  precondition: { label: '前置条件', icon: '📋' },
  execution:    { label: 'AutoGLM 执行', icon: '🤖' },
  report:       { label: '报告保存', icon: '📄' },
}

const ACTION_ICONS: Record<string, string> = {
  Tap: '👆', Click: '👆', Swipe: '👋', LongPress: '👇',
  Type: '⌨️', Back: '◀️', Home: '🏠', Launch: '📱',
  Wait: '⏳', finish: '✅', Note: '📝', Call_API: '🔌',
  Take_over: '🖐️', Interact: '🤖',
}

/* ------------------------------------------------------------------ */
/*  State                                                              */
/* ------------------------------------------------------------------ */

const collapsedPhases = ref<Record<string, boolean>>({})
const logContainer = ref<HTMLElement | null>(null)
const autoScroll = ref(true)

// Screenshot preview dialog
const previewVisible = ref(false)
const previewUrl = ref('')

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function phaseMeta(phase: string) {
  return PHASE_META[phase] ?? { label: phase, icon: '📌' }
}

function actionIcon(type: string | undefined): string {
  if (!type) return '▶️'
  return ACTION_ICONS[type] ?? '▶️'
}

function eventTypeClass(evt: TestCaseRunStreamEvent): string {
  if (evt.event === 'error' || evt.type === 'error' || evt.type === 'step_screenshot_failed')
    return 'error'
  if (evt.event === 'need_user') return 'warning'
  if (evt.event === 'result') return evt.run_result === 'passed' ? 'success' : 'error'
  if (evt.type === 'action_executed') return evt.success === false ? 'error' : 'success'
  if (evt.type === 'step_screenshot') return 'screenshot'
  if (evt.type === 'autoglm_auto_login') return 'info'
  return 'info'
}

function eventBadgeVariant(evt: TestCaseRunStreamEvent): string {
  const cls = eventTypeClass(evt)
  if (cls === 'error')   return 'danger'
  if (cls === 'warning') return 'warning'
  if (cls === 'success') return 'success'
  return 'info'
}

function eventLabel(evt: TestCaseRunStreamEvent): string {
  if (evt.step != null && evt.type === 'action_executed') return `步骤 ${evt.step}`
  if (evt.action_type) return evt.action_type as string
  if (evt.event === 'result') return '执行结果'
  if (evt.event === 'need_user') return '需介入'
  if (evt.type === 'autoglm_terminal_log') return '终端日志'
  if (evt.type === 'autoglm_auto_login') return '自动登录'
  if (evt.type === 'plan' || evt.type === 'case_task_plan') return '任务计划'
  if (evt.type === 'final_screenshot') return '最终截图'
  return evt.type || evt.event || '步骤'
}

function screenshotSrc(evt: TestCaseRunStreamEvent): string | null {
  const url = evt.screenshot_url || evt.screenshot_path || evt.screenshot
  if (!url || typeof url !== 'string') return null
  return url.startsWith('http') || url.startsWith('data:') ? url : getAssetUrl(url)
}

function formatTime(ts: string | null | undefined): string {
  if (!ts) return ''
  try {
    return new Date(ts).toLocaleTimeString('zh-CN', {
      hour: '2-digit', minute: '2-digit', second: '2-digit',
    })
  } catch { return '' }
}

/* ------------------------------------------------------------------ */
/*  Grouped events                                                     */
/* ------------------------------------------------------------------ */

const groupedEvents = computed(() => {
  const groups: { phase: string; events: TestCaseRunStreamEvent[] }[] = []
  for (const evt of props.events) {
    if (evt.type === 'step_screenshot') continue
    const phase = evt.phase || 'other'
    let group = groups.find(g => g.phase === phase)
    if (!group) { group = { phase, events: [] }; groups.push(group) }
    group.events.push(evt)
  }
  groups.sort((a, b) => {
    const ai = PHASE_ORDER.indexOf(a.phase as any)
    const bi = PHASE_ORDER.indexOf(b.phase as any)
    if (ai === -1 && bi === -1) return 0
    if (ai === -1) return 1
    if (bi === -1) return -1
    return ai - bi
  })
  return groups
})

const totalEventCount = computed(() =>
  groupedEvents.value.reduce((n, g) => n + g.events.length, 0)
)

/* ------------------------------------------------------------------ */
/*  Auto-scroll                                                        */
/* ------------------------------------------------------------------ */

watch(() => props.events.length, async () => {
  if (!autoScroll.value) return
  await nextTick()
  if (logContainer.value) {
    logContainer.value.scrollTop = logContainer.value.scrollHeight
  }
})

function onScroll() {
  if (!logContainer.value) return
  const { scrollTop, scrollHeight, clientHeight } = logContainer.value
  autoScroll.value = scrollHeight - scrollTop - clientHeight < 60
}

/* ------------------------------------------------------------------ */
/*  Phase collapse                                                     */
/* ------------------------------------------------------------------ */

function togglePhase(phase: string) {
  if (!props.collapsible) return
  collapsedPhases.value[phase] = !collapsedPhases.value[phase]
}

function isCollapsed(phase: string): boolean {
  return props.collapsible ? Boolean(collapsedPhases.value[phase]) : false
}

/* ------------------------------------------------------------------ */
/*  Screenshot preview                                                 */
/* ------------------------------------------------------------------ */

function openPreview(url: string) {
  previewUrl.value = url
  previewVisible.value = true
  emit('preview', url)
}
</script>

<template>
  <div class="step-log">
    <!-- Empty state -->
    <div v-if="!events.length" class="step-log__empty">
      <el-icon :size="32" color="var(--el-text-color-placeholder)"><Loading /></el-icon>
      <span>等待执行日志…</span>
    </div>

    <!-- Log content -->
    <template v-else>
      <!-- Header bar -->
      <div class="step-log__header">
        <span class="step-log__count">{{ totalEventCount }} 条日志</span>
        <el-tag
          v-if="!autoScroll"
          size="small"
          effect="plain"
          class="step-log__autoscroll-tag"
          @click="autoScroll = true"
        >
          <el-icon><ArrowDown /></el-icon> 滚动已暂停 · 点击恢复
        </el-tag>
      </div>

      <!-- Scrollable log area -->
      <div ref="logContainer" class="step-log__body" @scroll="onScroll">
        <div
          v-for="group in groupedEvents"
          :key="group.phase"
          class="step-log__phase"
        >
          <!-- Phase header -->
          <div
            class="step-log__phase-header"
            :class="{ 'step-log__phase-header--clickable': collapsible }"
            @click="togglePhase(group.phase)"
          >
            <el-icon v-if="collapsible" class="step-log__phase-toggle" :size="14">
              <ArrowDown v-if="!isCollapsed(group.phase)" />
              <ArrowRight v-else />
            </el-icon>
            <span class="step-log__phase-icon">{{ phaseMeta(group.phase).icon }}</span>
            <span class="step-log__phase-label">{{ phaseMeta(group.phase).label }}</span>
            <span class="step-log__phase-count">{{ group.events.length }}</span>
          </div>

          <!-- Phase events -->
          <Transition name="phase-slide">
            <div v-show="!isCollapsed(group.phase)" class="step-log__events">
              <div
                v-for="(evt, idx) in group.events"
                :key="idx"
                class="step-log__event"
                :class="[`step-log__event--${eventTypeClass(evt)}`]"
              >
                <!-- Timeline dot -->
                <span class="step-log__dot" />

                <!-- Time -->
                <span class="step-log__time">{{ formatTime(evt.timestamp) }}</span>

                <!-- Badge -->
                <span
                  class="step-log__badge"
                  :class="[`step-log__badge--${eventBadgeVariant(evt)}`]"
                >
                  <template v-if="evt.type === 'action_executed'">
                    {{ actionIcon(evt.action_type as string | undefined) }}
                  </template>
                  {{ eventLabel(evt) }}
                </span>

                <!-- Message -->
                <span class="step-log__msg">{{ evt.message || evt.result_note || evt.run_result || '' }}</span>

                <!-- Inline thumbnail -->
                <img
                  v-if="showScreenshots && screenshotSrc(evt)"
                  :src="screenshotSrc(evt)!"
                  class="step-log__thumb"
                  @click.stop="openPreview(screenshotSrc(evt)!)"
                />
              </div>
            </div>
          </Transition>
        </div>
      </div>

      <!-- Screenshot preview dialog -->
      <el-dialog
        v-model="previewVisible"
        :show-close="true"
        width="auto"
        class="step-log__preview-dialog"
        append-to-body
        destroy-on-close
      >
        <img :src="previewUrl" class="step-log__preview-img" />
      </el-dialog>
    </template>
  </div>
</template>

<style scoped>
/* ================================================================== */
/*  Root                                                               */
/* ================================================================== */

.step-log {
  --dot-size: 8px;
  --dot-color: var(--el-border-color);
  --dot-color-error: var(--el-color-danger);
  --dot-color-success: var(--el-color-success);
  --dot-color-warning: var(--el-color-warning);
  --dot-color-info: var(--el-color-primary-light-3);

  display: flex;
  flex-direction: column;
  gap: 0;
  font-size: 13px;
  line-height: 1.5;
  color: var(--el-text-color-regular);
}

/* ================================================================== */
/*  Empty state                                                        */
/* ================================================================== */

.step-log__empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 32px 0;
  color: var(--el-text-color-placeholder);
  font-size: 13px;
}

/* ================================================================== */
/*  Header bar                                                         */
/* ================================================================== */

.step-log__header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 6px 12px;
  border-bottom: 1px solid var(--el-border-color-lighter);
  background: var(--el-fill-color-lighter);
  border-radius: 8px 8px 0 0;
}

.step-log__count {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.step-log__autoscroll-tag {
  cursor: pointer;
  font-size: 11px;
}

/* ================================================================== */
/*  Scrollable body                                                    */
/* ================================================================== */

.step-log__body {
  max-height: 70vh;
  overflow-y: auto;
  padding: 0 4px;
  border-radius: 0 0 8px 8px;
  border: 1px solid var(--el-border-color-lighter);
  border-top: none;
  background: var(--el-bg-color);
}

.step-log__body::-webkit-scrollbar { width: 6px; }
.step-log__body::-webkit-scrollbar-track { background: transparent; }
.step-log__body::-webkit-scrollbar-thumb {
  background: var(--el-border-color);
  border-radius: 3px;
}
.step-log__body::-webkit-scrollbar-thumb:hover {
  background: var(--el-border-color-darker);
}

/* ================================================================== */
/*  Phase group                                                        */
/* ================================================================== */

.step-log__phase {
  border-bottom: 1px solid var(--el-border-color-extra-light);
}
.step-log__phase:last-child { border-bottom: none; }

.step-log__phase-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  background: var(--el-fill-color-lighter);
  position: sticky;
  top: 0;
  z-index: 1;
  user-select: none;
}

.step-log__phase-header--clickable { cursor: pointer; }
.step-log__phase-header--clickable:hover {
  background: var(--el-fill-color-light);
}

.step-log__phase-toggle {
  color: var(--el-text-color-secondary);
  flex-shrink: 0;
}

.step-log__phase-icon {
  font-size: 14px;
  flex-shrink: 0;
}

.step-log__phase-label {
  font-weight: 600;
  font-size: 13px;
  color: var(--el-text-color-primary);
  flex: 1;
}

.step-log__phase-count {
  font-size: 11px;
  color: var(--el-text-color-secondary);
  background: var(--el-fill-color);
  padding: 1px 8px;
  border-radius: 10px;
  min-width: 22px;
  text-align: center;
}

/* ================================================================== */
/*  Event list                                                         */
/* ================================================================== */

.step-log__events {
  padding: 4px 0 4px 0;
}

/* Slide transition */
.phase-slide-enter-active,
.phase-slide-leave-active {
  transition: all 0.2s ease;
  overflow: hidden;
}
.phase-slide-enter-from,
.phase-slide-leave-to {
  opacity: 0;
  max-height: 0;
  padding-top: 0;
  padding-bottom: 0;
}

/* ================================================================== */
/*  Single event row                                                   */
/* ================================================================== */

.step-log__event {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 6px 12px 6px 20px;
  position: relative;
  min-height: 28px;
}

/* Vertical timeline line */
.step-log__event::before {
  content: '';
  position: absolute;
  left: 15px;
  top: 0;
  bottom: 0;
  width: 1px;
  background: var(--el-border-color-lighter);
}
.step-log__event:first-child::before { top: 50%; }
.step-log__event:last-child::before  { bottom: 50%; }

/* Timeline dot */
.step-log__dot {
  position: absolute;
  left: 11px;
  top: 11px;
  width: var(--dot-size);
  height: var(--dot-size);
  border-radius: 50%;
  background: var(--dot-color);
  border: 2px solid var(--el-bg-color);
  z-index: 1;
  flex-shrink: 0;
}

.step-log__event--error   .step-log__dot { background: var(--dot-color-error); }
.step-log__event--success .step-log__dot { background: var(--dot-color-success); }
.step-log__event--warning .step-log__dot { background: var(--dot-color-warning); }
.step-log__event--info    .step-log__dot { background: var(--dot-color-info); }

/* Time */
.step-log__time {
  font-size: 11px;
  color: var(--el-text-color-placeholder);
  white-space: nowrap;
  min-width: 66px;
  padding-top: 1px;
  font-variant-numeric: tabular-nums;
}

/* Badge / tag */
.step-log__badge {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
  padding: 1px 7px;
  border-radius: 4px;
  flex-shrink: 0;
  line-height: 1.6;
}
.step-log__badge--danger  { color: var(--el-color-danger);  background: var(--el-color-danger-light-9); }
.step-log__badge--warning { color: var(--el-color-warning); background: var(--el-color-warning-light-9); }
.step-log__badge--success { color: var(--el-color-success); background: var(--el-color-success-light-9); }
.step-log__badge--info    { color: var(--el-color-primary); background: var(--el-color-primary-light-9); }

/* Message */
.step-log__msg {
  flex: 1;
  font-size: 12px;
  line-height: 1.5;
  color: var(--el-text-color-regular);
  word-break: break-word;
  overflow-wrap: break-word;
}

.step-log__event--error .step-log__msg {
  color: var(--el-color-danger);
  font-weight: 500;
}

.step-log__event--success .step-log__msg {
  color: var(--el-text-color-regular);
}

/* Inline thumbnail */
.step-log__thumb {
  height: 40px;
  max-width: 24px;
  object-fit: contain;
  border-radius: 4px;
  border: 1px solid var(--el-border-color-light);
  cursor: pointer;
  flex-shrink: 0;
  background: var(--el-fill-color-lighter);
  transition: all 0.15s ease;
  align-self: center;
}

.step-log__thumb:hover {
  border-color: var(--el-color-primary);
  transform: scale(1.15);
  box-shadow: 0 2px 8px var(--el-color-primary-light-7);
}

/* ================================================================== */
/*  Screenshot preview dialog                                          */
/* ================================================================== */

.step-log__preview-dialog :deep(.el-dialog__body) {
  padding: 8px;
  display: flex;
  justify-content: center;
  align-items: center;
  background: var(--el-fill-color-lighter);
}

.step-log__preview-img {
  max-width: 90vw;
  max-height: 80vh;
  object-fit: contain;
  border-radius: 4px;
}

/* ================================================================== */
/*  Result event (special styling)                                     */
/* ================================================================== */

.step-log__event--error.step-log__event--error {
  background: var(--el-color-danger-light-9);
  border-radius: 4px;
  margin: 2px 8px;
}

.step-log__event--warning {
  background: var(--el-color-warning-light-9);
  border-radius: 4px;
  margin: 2px 8px;
}
</style>
