<script setup lang="ts">
import { Setting, Check, VideoPlay } from '@element-plus/icons-vue'

defineProps<{
  modelConfig: any
  modelPresets: any[]
  modelForm: any
  modelBusy: boolean
  modelTesting: boolean
  currentModelLabel: string
  apiKeyPlaceholder: string
}>()

const emit = defineEmits<{
  'apply-preset': [preset: any]
  save: []
  test: []
}>()
</script>

<template>
  <section class="panel-section model-panel">
    <div class="section-title">模型配置</div>

    <div v-if="currentModelLabel" class="current-model">
      <span class="info-label">当前模型:</span>
      <el-tag size="small" type="info">{{ currentModelLabel }}</el-tag>
    </div>

    <div v-if="modelPresets?.length" class="preset-list">
      <span class="info-label">预设:</span>
      <el-button-group size="small">
        <el-button
          v-for="preset in modelPresets"
          :key="preset.name"
          size="small"
          @click="emit('apply-preset', preset)"
        >
          {{ preset.label || preset.name }}
        </el-button>
      </el-button-group>
    </div>

    <div class="model-actions">
      <el-button
        :icon="Check"
        size="small"
        type="primary"
        :loading="modelBusy"
        @click="emit('save')"
      >
        保存
      </el-button>
      <el-button
        :icon="VideoPlay"
        size="small"
        :loading="modelTesting"
        @click="emit('test')"
      >
        测试
      </el-button>
    </div>
  </section>
</template>

<style scoped>
.panel-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.model-panel {
  padding-bottom: 10px;
  border-bottom: 1px solid var(--border-color);
}

.section-title {
  color: var(--text-primary);
  font-size: 12px;
  font-weight: 700;
}

.current-model {
  display: flex;
  align-items: center;
  gap: 6px;
}

.info-label {
  color: var(--text-muted);
  font-size: 12px;
}

.preset-list {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.model-actions {
  display: flex;
  gap: 6px;
}
</style>
