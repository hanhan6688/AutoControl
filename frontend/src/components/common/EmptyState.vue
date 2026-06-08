<script setup lang="ts">
import { FolderOpened } from '@element-plus/icons-vue'

defineProps<{
  icon?: any
  title?: string
  description?: string
}>()
</script>

<template>
  <div class="empty-state">
    <el-icon :size="64" class="empty-icon">
      <component :is="icon || FolderOpened" />
    </el-icon>
    <h3 class="empty-title">{{ title || '暂无数据' }}</h3>
    <p v-if="description" class="empty-description">{{ description }}</p>
    <div v-if="$slots.default" class="empty-action">
      <slot />
    </div>
  </div>
</template>

<style scoped>
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 48px 24px;
  text-align: center;
}

.empty-icon {
  color: var(--el-text-color-placeholder);
  margin-bottom: 16px;
}

.empty-title {
  font-size: 16px;
  font-weight: 500;
  color: var(--el-text-color-regular);
  margin: 0 0 8px;
}

.empty-description {
  font-size: 14px;
  color: var(--el-text-color-secondary);
  margin: 0 0 16px;
}

.empty-action {
  margin-top: 8px;
}
</style>
