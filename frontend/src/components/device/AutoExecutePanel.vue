<script setup lang="ts">
import { ArrowDown, CircleClose, VideoPlay, CircleCheck } from '@element-plus/icons-vue'

defineProps<{
  recording: boolean
  playing: boolean
  packageName: string
  activeScriptPath: string | null
  platform?: string | null
  statusText?: string
  locateBusy?: boolean
}>()

const emit = defineEmits<{
  startRecording: []
  playback: []
  addAssert: [type: string]
}>()

const assertTypes = [
  { label: '文本可见', value: 'text_visible' },
  { label: '元素存在', value: 'element_exists' },
  { label: 'OCR 包含', value: 'ocr_contains' },
  { label: '图像对比', value: 'image_exists' },
  { label: 'App 前台', value: 'app_foreground' },
]
</script>

<template>
  <div class="autoexecute-panel" :class="{ recording }">
    <div class="autoexecute-buttons">
      <el-button
        :type="recording ? 'danger' : 'primary'"
        size="small"
        :loading="playing"
        @click="emit('startRecording')"
      >
        <el-icon v-if="recording"><CircleClose /></el-icon>
        <el-icon v-else><VideoPlay /></el-icon>
        {{ recording ? '停止录制' : '控件录制' }}
      </el-button>
      <el-button
        type="default"
        size="small"
        :disabled="recording || !activeScriptPath"
        :loading="playing"
        @click="emit('playback')"
      >
        <el-icon><VideoPlay /></el-icon>
        录制回放
      </el-button>
    </div>

    <!-- Assertion type selector -->
    <el-dropdown v-if="recording" trigger="click" @command="(cmd: string) => emit('addAssert', cmd)">
      <el-button size="small" type="success">
        <el-icon><CircleCheck /></el-icon>
        添加断言
        <el-icon class="el-icon--right"><ArrowDown /></el-icon>
      </el-button>
      <template #dropdown>
        <el-dropdown-menu>
          <el-dropdown-item
            v-for="at in assertTypes"
            :key="at.value"
            :command="at.value"
          >
            {{ at.label }}
          </el-dropdown-item>
        </el-dropdown-menu>
      </template>
    </el-dropdown>

    <div v-if="packageName" class="package-info">
      <span class="package-label">{{ platform === 'ios' ? 'Bundle ID:' : '应用 ID:' }}</span>
      <span class="package-value">{{ packageName }}</span>
    </div>

    <div class="autoexecute-hint" :class="{ recording }">
      <template v-if="recording">
        <span class="recording-dot"></span>
        {{ statusText || '点击画面录制控件操作' }}
        <span v-if="locateBusy" class="locating-text">定位中...</span>
      </template>
      <template v-else>
        {{ statusText || '点击"控件录制"选择目标应用' }}
      </template>
    </div>
  </div>
</template>

<style scoped>
.autoexecute-panel {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  background: var(--bg-secondary);
  transition: border-color 0.2s, background 0.2s;
}

.autoexecute-panel.recording {
  border-color: var(--danger);
  background: rgba(245, 108, 108, 0.08);
}

.autoexecute-buttons {
  display: flex;
  gap: 8px;
}

.package-info {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  background: var(--bg-tertiary);
  border-radius: 4px;
  font-size: 11px;
}

.package-label {
  color: var(--text-muted);
}

.package-value {
  color: var(--accent);
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  word-break: break-all;
}

.autoexecute-hint {
  font-size: 11px;
  color: var(--text-muted);
  line-height: 1.4;
  display: flex;
  align-items: center;
  gap: 6px;
}

.autoexecute-hint.recording {
  color: var(--danger);
  font-weight: 500;
}

.recording-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--danger);
  animation: pulse 1s infinite;
}

.locating-text {
  color: var(--accent);
  font-weight: 500;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}
</style>
