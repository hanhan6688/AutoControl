<script setup lang="ts">
import { computed } from 'vue'
import { CircleCheck, Document, Picture } from '@element-plus/icons-vue'
import type { ImageCompareResponse } from '../../api'

type AutomationAssertType = 'element_exists' | 'text_visible' | 'ocr_contains' | 'image_exists' | 'app_foreground'

const props = defineProps<{
  deviceReady: boolean
  scriptReady: boolean
  recording: boolean
  activeScriptPath: string | null
  statusText?: string
  assertType: AutomationAssertType
  assertTargetText: string
  assertTargetResourceId: string
  assertTargetAppId: string
  assertImageThreshold: number
  assertImageTemplateName: string
  imageCompareBusy: boolean
  imageCompareResult: ImageCompareResponse | null
}>()

const emit = defineEmits<{
  updateAssertType: [value: AutomationAssertType]
  updateAssertTargetText: [value: string]
  updateAssertTargetResourceId: [value: string]
  updateAssertTargetAppId: [value: string]
  updateAssertImageThreshold: [value: number]
  updateAssertImageTemplateName: [value: string]
  addAssert: []
  captureTemplate: []
  runImageCompare: []
}>()

const assertTypeModel = computed({
  get: () => props.assertType,
  set: value => emit('updateAssertType', value),
})

const assertTargetTextModel = computed({
  get: () => props.assertTargetText,
  set: value => emit('updateAssertTargetText', value),
})

const assertTargetResourceIdModel = computed({
  get: () => props.assertTargetResourceId,
  set: value => emit('updateAssertTargetResourceId', value),
})

const assertTargetAppIdModel = computed({
  get: () => props.assertTargetAppId,
  set: value => emit('updateAssertTargetAppId', value),
})

const assertImageThresholdModel = computed({
  get: () => props.assertImageThreshold,
  set: value => emit('updateAssertImageThreshold', value),
})

const assertImageTemplateNameModel = computed({
  get: () => props.assertImageTemplateName,
  set: value => emit('updateAssertImageTemplateName', value),
})
</script>

<template>
  <div class="automation-sidebar">
    <div class="automation-section">
      <div class="automation-section-title">
        <el-icon><CircleCheck /></el-icon>
        <span>断言</span>
      </div>
      <el-select v-model="assertTypeModel" size="small" class="assert-type-select">
        <el-option label="文本可见" value="text_visible" />
        <el-option label="元素存在" value="element_exists" />
        <el-option label="OCR 包含" value="ocr_contains" />
        <el-option label="图像对比" value="image_exists" />
        <el-option label="App 前台" value="app_foreground" />
      </el-select>

      <el-input
        v-if="assertTypeModel === 'text_visible' || assertTypeModel === 'ocr_contains'"
        v-model="assertTargetTextModel"
        size="small"
        placeholder="输入验证文本"
      />

      <el-input
        v-if="assertTypeModel === 'element_exists'"
        v-model="assertTargetResourceIdModel"
        size="small"
        placeholder="Resource ID，如 com.demo:id/btn"
      />

      <el-input
        v-if="assertTypeModel === 'app_foreground'"
        v-model="assertTargetAppIdModel"
        size="small"
        placeholder="包名 / Bundle ID"
      />

      <template v-if="assertTypeModel === 'image_exists'">
        <el-input
          v-model="assertImageTemplateNameModel"
          size="small"
          placeholder="模板图片路径"
        />
        <div class="threshold-row">
          <span>阈值</span>
          <el-slider v-model="assertImageThresholdModel" :min="0.7" :max="1" :step="0.01" size="small" />
        </div>
      </template>

      <el-button
        size="small"
        type="primary"
        :disabled="!deviceReady || !scriptReady"
        @click="emit('addAssert')"
      >
        写入断言
      </el-button>
      <div class="automation-hint">
        {{ recording ? '录制开启时会直接写入当前脚本。' : '录制关闭时先配置参数，开始录制后再写入脚本。' }}
      </div>
    </div>

    <div class="automation-section">
      <div class="automation-section-title">
        <el-icon><Picture /></el-icon>
        <span>图像对比</span>
      </div>
      <el-input
        v-model="assertImageTemplateNameModel"
        size="small"
        placeholder="模板图片路径"
      />
      <div class="threshold-row">
        <span>阈值</span>
        <el-slider v-model="assertImageThresholdModel" :min="0.7" :max="1" :step="0.01" size="small" />
      </div>
      <div class="automation-actions">
        <el-button
          size="small"
          :loading="imageCompareBusy"
          :disabled="!deviceReady"
          @click="emit('captureTemplate')"
        >
          截取基准图
        </el-button>
        <el-button
          size="small"
          :loading="imageCompareBusy"
          :disabled="!deviceReady || !assertImageTemplateName"
          @click="emit('runImageCompare')"
        >
          对比当前画面
        </el-button>
      </div>
      <div v-if="imageCompareResult" class="compare-result">
        <el-tag :type="imageCompareResult.matched ? 'success' : 'danger'" size="small">
          {{ imageCompareResult.matched ? '匹配' : '未匹配' }}
        </el-tag>
        <span class="compare-score">得分: {{ imageCompareResult.score.toFixed(2) }}</span>
      </div>
    </div>

    <div class="automation-section">
      <div class="automation-section-title">
        <el-icon><Document /></el-icon>
        <span>自动化脚本</span>
      </div>
      <div class="script-path">
        {{ activeScriptPath || '未打开脚本' }}
      </div>
      <div class="automation-hint">
        底部面板负责控件录制和回放；左侧这里负责补断言、模板和图像对比步骤。
      </div>
      <div v-if="statusText" class="script-status">
        {{ statusText }}
      </div>
    </div>
  </div>
</template>

<style scoped>
.automation-sidebar {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 10px 12px;
}

.automation-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  background: var(--bg-secondary);
}

.automation-section-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
}

.assert-type-select {
  width: 100%;
}

.threshold-row {
  display: grid;
  grid-template-columns: 34px minmax(0, 1fr);
  align-items: center;
  gap: 8px;
  color: var(--text-muted);
  font-size: 12px;
}

.automation-actions {
  display: flex;
  gap: 8px;
}

.automation-hint,
.script-status {
  font-size: 11px;
  line-height: 1.4;
  color: var(--text-muted);
}

.script-path {
  padding: 6px 8px;
  border-radius: 4px;
  background: var(--bg-tertiary);
  color: var(--accent);
  font-size: 11px;
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  word-break: break-all;
}

.compare-result {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border: 1px solid var(--border-color);
  border-radius: 4px;
  background: var(--bg-tertiary);
}

.compare-score {
  font-size: 12px;
  color: var(--text-secondary);
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
}
</style>
