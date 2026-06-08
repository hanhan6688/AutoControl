<script setup lang="ts">
import {
  Camera,
  Refresh,
  VideoCamera,
  Search,
  Pointer,
  Edit,
  Position,
  Expand,
} from '@element-plus/icons-vue'

defineProps<{
  latestScreenshot: string
  connected: boolean
  pcRecordingEnabled: boolean
  pcGeneratedCode: string
  pcSelectedElement: any
  screenshotClickEnabled: boolean
  autoRefreshActive: boolean
  quickActionBusy: boolean
}>()

const emit = defineEmits<{
  'screenshot-click': [event: any]
  'toggle-recording': []
  'capture-screenshot': []
  'refresh-snapshot': []
  'click-element': []
  'toggle-auto-refresh': []
  'find-and-click': [label: string]
  'find-and-fill': [label: string, text: string]
  'press-key': [key: string]
  'scroll-page': [direction: string, amount: number]
  preview: [url: string]
}>()
</script>

<template>
  <section class="panel-section screenshot-panel">
    <div class="section-title">浏览器截图</div>

    <div class="screenshot-container">
      <img
        v-if="latestScreenshot"
        :src="latestScreenshot"
        alt="浏览器截图"
        class="screenshot-img"
        :class="{ 'click-enabled': screenshotClickEnabled }"
        @click="emit('screenshot-click', $event)"
      />
      <el-empty v-else description="暂无截图" :image-size="80" />
    </div>

    <div class="screenshot-actions">
      <el-button-group>
        <el-tooltip content="截图" placement="top">
          <el-button :icon="Camera" size="small" :disabled="!connected" @click="emit('capture-screenshot')" />
        </el-tooltip>
        <el-tooltip content="刷新" placement="top">
          <el-button :icon="Refresh" size="small" :disabled="!connected" @click="emit('refresh-snapshot')" />
        </el-tooltip>
        <el-tooltip content="录制" placement="top">
          <el-button
            :icon="VideoCamera"
            size="small"
            :type="pcRecordingEnabled ? 'danger' : 'default'"
            :disabled="!connected"
            @click="emit('toggle-recording')"
          />
        </el-tooltip>
        <el-tooltip content="自动刷新" placement="top">
          <el-button
            size="small"
            :type="autoRefreshActive ? 'success' : 'default'"
            :disabled="!connected"
            @click="emit('toggle-auto-refresh')"
          >
            自动
          </el-button>
        </el-tooltip>
      </el-button-group>

      <el-button-group>
        <el-tooltip content="点击元素" placement="top">
          <el-button :icon="Pointer" size="small" :disabled="!connected || !pcSelectedElement" @click="emit('click-element')" />
        </el-tooltip>
        <el-tooltip content="查找并点击" placement="top">
          <el-button :icon="Search" size="small" :disabled="!connected" @click="emit('find-and-click', '')" />
        </el-tooltip>
        <el-tooltip content="查找并填写" placement="top">
          <el-button :icon="Edit" size="small" :disabled="!connected" @click="emit('find-and-fill', '', '')" />
        </el-tooltip>
      </el-button-group>

      <el-button-group>
        <el-tooltip content="按键" placement="top">
          <el-button :icon="Position" size="small" :disabled="!connected" @click="emit('press-key', 'Enter')" />
        </el-tooltip>
        <el-tooltip content="滚动" placement="top">
          <el-button :icon="Expand" size="small" :disabled="!connected" @click="emit('scroll-page', 'down', 300)" />
        </el-tooltip>
      </el-button-group>
    </div>

    <div v-if="pcSelectedElement" class="selected-element-info">
      <span class="info-label">选中元素:</span>
      <span class="info-value">{{ pcSelectedElement }}</span>
    </div>

    <div v-if="pcGeneratedCode" class="generated-code">
      <div class="info-label">生成代码:</div>
      <pre class="code-block">{{ pcGeneratedCode }}</pre>
    </div>
  </section>
</template>

<style scoped>
.panel-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.section-title {
  color: var(--text-primary);
  font-size: 12px;
  font-weight: 700;
}

.screenshot-container {
  flex: 1;
  min-height: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-primary);
  border-radius: 4px;
  overflow: hidden;
}

.screenshot-img {
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
}

.screenshot-img.click-enabled {
  cursor: crosshair;
}

.screenshot-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.selected-element-info {
  display: flex;
  gap: 4px;
  font-size: 12px;
}

.info-label {
  color: var(--text-muted);
  font-size: 12px;
}

.info-value {
  color: var(--text-primary);
  font-size: 12px;
  word-break: break-all;
}

.generated-code {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.code-block {
  margin: 0;
  padding: 6px 8px;
  background: var(--bg-primary);
  border-radius: 4px;
  font-size: 11px;
  max-height: 120px;
  overflow: auto;
  white-space: pre-wrap;
}
</style>
