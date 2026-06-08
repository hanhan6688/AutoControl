<script setup lang="ts">
import { ref, computed } from 'vue'
import { Search, Picture } from '@element-plus/icons-vue'

defineProps<{
  disabled?: boolean
}>()

const emit = defineEmits<{
  ocrClick: [text: string, contains: boolean]
  templateClick: [file: File, threshold: number]
}>()

const ocrText = ref('')
const ocrContains = ref(true)
const templateFile = ref<File | null>(null)
const templateThreshold = ref(0.92)

function handleOcrClick() {
  if (ocrText.value.trim()) {
    emit('ocrClick', ocrText.value.trim(), ocrContains.value)
  }
}

function handleTemplateSelect(event: Event) {
  const target = event.target as HTMLInputElement
  if (target.files?.length) {
    templateFile.value = target.files[0]
  }
}

function handleTemplateClick() {
  if (templateFile.value) {
    emit('templateClick', templateFile.value, templateThreshold.value)
  }
}
</script>

<template>
  <div class="screen-controls">
    <div class="control-group">
      <span class="control-label">OCR 点击:</span>
      <el-input
        v-model="ocrText"
        placeholder="输入文字"
        size="small"
        style="width: 150px"
        :disabled="disabled"
        @keyup.enter="handleOcrClick"
      />
      <el-checkbox v-model="ocrContains" :disabled="disabled">模糊匹配</el-checkbox>
      <el-button
        type="primary"
        size="small"
        :disabled="disabled || !ocrText.trim()"
        @click="handleOcrClick"
      >
        点击
      </el-button>
    </div>

    <div class="control-group">
      <span class="control-label">图像点击:</span>
      <el-upload
        :show-file-list="false"
        accept="image/*"
        :disabled="disabled"
        :on-change="(file: any) => templateFile = file.raw"
      >
        <el-button size="small" :disabled="disabled">
          <el-icon class="el-icon--left"><Picture /></el-icon>
          选择图片
        </el-button>
      </el-upload>
      <el-input-number
        v-model="templateThreshold"
        :min="0.5"
        :max="1"
        :step="0.05"
        :precision="2"
        size="small"
        style="width: 100px"
        :disabled="disabled"
      />
      <el-button
        type="primary"
        size="small"
        :disabled="disabled || !templateFile"
        @click="handleTemplateClick"
      >
        点击
      </el-button>
    </div>
  </div>
</template>

<style scoped>
.screen-controls {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 12px;
  background: var(--el-bg-color);
  border-radius: 8px;
}

.control-group {
  display: flex;
  align-items: center;
  gap: 8px;
}

.control-label {
  font-size: 13px;
  color: var(--el-text-color-secondary);
  min-width: 70px;
}
</style>
