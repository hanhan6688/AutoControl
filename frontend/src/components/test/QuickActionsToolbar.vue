<script setup lang="ts">
import { computed } from 'vue'
import { VideoPlay, Close, Refresh, DocumentCopy } from '@element-plus/icons-vue'

const props = defineProps<{
  running: boolean
  hasSelection: boolean
  canRun: boolean
  canStop: boolean
}>()

const emit = defineEmits<{
  runSelected: []
  runAll: []
  stop: []
  refresh: []
  copyResults: []
}>()

const runButtonText = computed(() => props.running ? '执行中...' : '执行选中')
</script>

<template>
  <div class="quick-actions-toolbar">
    <el-button-group>
      <el-tooltip content="执行选中的用例" placement="top">
        <el-button
          :icon="VideoPlay"
          type="primary"
          size="small"
          :loading="running"
          :disabled="!canRun || running"
          @click="emit('runSelected')"
        >
          {{ runButtonText }}
        </el-button>
      </el-tooltip>
      <el-tooltip content="批量执行全部用例" placement="top">
        <el-button
          size="small"
          :disabled="!canRun || running"
          @click="emit('runAll')"
        >
          全部执行
        </el-button>
      </el-tooltip>
    </el-button-group>

    <el-button-group>
      <el-tooltip content="停止当前执行" placement="top">
        <el-button
          :icon="Close"
          type="danger"
          size="small"
          :disabled="!canStop"
          @click="emit('stop')"
        >
          停止
        </el-button>
      </el-tooltip>
      <el-tooltip content="刷新用例列表" placement="top">
        <el-button
          :icon="Refresh"
          size="small"
          @click="emit('refresh')"
        >
          刷新
        </el-button>
      </el-tooltip>
    </el-button-group>

    <el-tooltip content="复制执行结果" placement="top">
      <el-button
        :icon="DocumentCopy"
        size="small"
        :disabled="!hasSelection"
        @click="emit('copyResults')"
      >
        复制结果
      </el-button>
    </el-tooltip>
  </div>
</template>

<style scoped>
.quick-actions-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 12px;
  background: var(--el-bg-color);
  border-radius: 6px;
  border: 1px solid var(--el-border-color-light);
}
</style>