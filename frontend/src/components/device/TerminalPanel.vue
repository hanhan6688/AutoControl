<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { Delete, DocumentCopy, Check } from '@element-plus/icons-vue'
import type { TerminalLine } from '../../composables/useScriptTerminal'

const props = defineProps<{
  lines: TerminalLine[]
  isRunning: boolean
  isConnected: boolean
  lastReturnCode: number | null
  durationMs: number | null
}>()

const emit = defineEmits<{
  clear: []
  cancel: []
}>()

const terminalRef = ref<HTMLElement | null>(null)
const autoScroll = ref(true)
const copied = ref(false)

const statusText = computed(() => {
  if (props.isRunning) return 'Running...'
  if (props.lastReturnCode !== null) {
    return props.lastReturnCode === 0
      ? `Completed (${props.durationMs}ms)`
      : `Failed (code ${props.lastReturnCode})`
  }
  return 'Idle'
})

const statusClass = computed(() => {
  if (props.isRunning) return 'status-running'
  if (props.lastReturnCode === 0) return 'status-success'
  if (props.lastReturnCode !== null) return 'status-error'
  return ''
})

watch(() => props.lines.length, async () => {
  if (autoScroll.value) {
    await nextTick()
    if (terminalRef.value) {
      terminalRef.value.scrollTop = terminalRef.value.scrollHeight
    }
  }
})

function getLineClass(line: TerminalLine): string {
  switch (line.type) {
    case 'stdout': return 'line-stdout'
    case 'stderr': return 'line-stderr'
    case 'system': return 'line-system'
    case 'exit': return line.text.includes('code 0') ? 'line-exit-success' : 'line-exit-error'
    default: return ''
  }
}

async function copyOutput() {
  const text = props.lines.map(l => l.text).join('\n')
  await navigator.clipboard.writeText(text)
  copied.value = true
  setTimeout(() => { copied.value = false }, 2000)
}

function handleScroll() {
  if (!terminalRef.value) return
  const { scrollTop, scrollHeight, clientHeight } = terminalRef.value
  autoScroll.value = scrollTop + clientHeight >= scrollHeight - 10
}
</script>

<template>
  <div class="terminal-panel">
    <div class="terminal-header">
      <div class="terminal-status">
        <span class="status-indicator" :class="statusClass"></span>
        <span class="status-text">{{ statusText }}</span>
      </div>
      <div class="terminal-actions">
        <el-button
          v-if="isRunning"
          size="small"
          type="danger"
          @click="emit('cancel')"
        >
          Cancel
        </el-button>
        <el-tooltip content="Copy output" placement="top">
          <el-button size="small" :icon="copied ? Check : DocumentCopy" @click="copyOutput" />
        </el-tooltip>
        <el-tooltip content="Clear" placement="top">
          <el-button size="small" :icon="Delete" @click="emit('clear')" />
        </el-tooltip>
      </div>
    </div>
    <div
      ref="terminalRef"
      class="terminal-content"
      @scroll="handleScroll"
    >
      <div
        v-for="line in lines"
        :key="line.id"
        class="terminal-line"
        :class="getLineClass(line)"
      >
        {{ line.text }}
      </div>
      <div v-if="lines.length === 0" class="terminal-empty">
        No output yet. Run a script to see output here.
      </div>
    </div>
  </div>
</template>

<style scoped>
.terminal-panel {
  display: flex;
  flex-direction: column;
  background: #1e1e1e;
  border-top: 1px solid #333;
  min-height: 120px;
  max-height: 300px;
}

.terminal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 6px 10px;
  background: #252526;
  border-bottom: 1px solid #333;
}

.terminal-status {
  display: flex;
  align-items: center;
  gap: 8px;
}

.status-indicator {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #666;
}

.status-indicator.status-running {
  background: #f0ad4e;
  animation: pulse 1s infinite;
}

.status-indicator.status-success {
  background: #5cb85c;
}

.status-indicator.status-error {
  background: #d9534f;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

.status-text {
  font-size: 12px;
  color: #ccc;
}

.terminal-actions {
  display: flex;
  gap: 4px;
}

.terminal-content {
  flex: 1;
  overflow: auto;
  padding: 8px 10px;
  font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
  font-size: 12px;
  line-height: 1.5;
}

.terminal-line {
  white-space: pre-wrap;
  word-break: break-all;
}

.line-stdout {
  color: #d4d4d4;
}

.line-stderr {
  color: #f48771;
}

.line-system {
  color: #6a9955;
}

.line-exit-success {
  color: #4ec9b0;
}

.line-exit-error {
  color: #f14c14;
}

.terminal-empty {
  color: #666;
  font-style: italic;
}
</style>