<script setup lang="ts">
import { View } from '@element-plus/icons-vue'

defineProps<{
  events: any[]
}>()

const emit = defineEmits<{
  preview: [url: string]
}>()
</script>

<template>
  <section class="panel-section unified-log">
    <div class="section-title">执行日志</div>
    <div v-if="events?.length" class="log-items">
      <div
        v-for="(evt, idx) in events"
        :key="idx"
        class="log-item"
        :class="evt.type || 'info'"
      >
        <span class="log-time">{{ evt.time || evt.timestamp || '' }}</span>
        <el-tag
          :type="evt.event === 'error' ? 'danger' : evt.event === 'need_user' ? 'warning' : evt.event === 'result' && evt.run_result === 'passed' ? 'success' : evt.type === 'error' ? 'danger' : evt.type === 'warning' ? 'warning' : evt.type === 'success' ? 'success' : 'info'"
          size="small"
        >
          {{ evt.step ? `步骤${evt.step}` : evt.action || evt.event || evt.type || '步骤' }}
        </el-tag>
        <span class="log-text">{{ evt.message || evt.text || evt.content || '' }}</span>
        <el-button
          v-if="evt.screenshot_url || evt.screenshot_path || evt.screenshot || evt.image"
          :icon="View"
          size="small"
          @click="emit('preview', evt.screenshot_url || evt.screenshot_path || evt.screenshot || evt.image)"
        />
      </div>
    </div>
    <el-empty v-else description="暂无日志" :image-size="40" />
  </section>
</template>

<style scoped>
.panel-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.unified-log {
  padding-bottom: 10px;
  border-bottom: 1px solid var(--border-color);
}

.section-title {
  color: var(--text-primary);
  font-size: 12px;
  font-weight: 700;
}

.log-items {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 200px;
  overflow: auto;
}

.log-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 6px;
  border-radius: 4px;
  background: var(--bg-primary);
  font-size: 12px;
}

.log-time {
  color: var(--text-muted);
  font-size: 11px;
  white-space: nowrap;
}

.log-text {
  color: var(--text-primary);
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}
</style>
