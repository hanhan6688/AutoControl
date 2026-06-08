<script setup lang="ts">
import { Link } from '@element-plus/icons-vue'

defineProps<{
  browserUrl: string
  browserTitle: string
}>()
</script>

<template>
  <section class="panel-section page-info">
    <div class="section-title">页面信息</div>
    <div v-if="browserUrl || browserTitle" class="info-list">
      <div v-if="browserTitle" class="info-row">
        <span class="info-label">标题:</span>
        <span class="info-value">{{ browserTitle }}</span>
      </div>
      <div v-if="browserUrl" class="info-row">
        <span class="info-label">地址:</span>
        <span class="info-value url-value">{{ browserUrl }}</span>
      </div>
    </div>
    <el-empty v-else description="暂无页面信息" :image-size="40" />
  </section>
</template>

<style scoped>
.panel-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.page-info {
  padding-bottom: 10px;
  border-bottom: 1px solid var(--border-color);
}

.section-title {
  color: var(--text-primary);
  font-size: 12px;
  font-weight: 700;
}

.info-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.info-row {
  display: flex;
  gap: 4px;
  font-size: 12px;
}

.info-label {
  color: var(--text-muted);
  font-size: 12px;
  white-space: nowrap;
}

.info-value {
  color: var(--text-primary);
  font-size: 12px;
  word-break: break-all;
}

.url-value {
  color: var(--el-color-primary);
}
</style>
