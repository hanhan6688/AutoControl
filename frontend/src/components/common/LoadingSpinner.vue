<script setup lang="ts">
defineProps<{
  size?: 'small' | 'default' | 'large'
  text?: string
}>()
</script>

<template>
  <div class="loading-spinner" :class="`loading-spinner--${size || 'default'}`">
    <el-icon class="is-loading" :size="size === 'small' ? 16 : size === 'large' ? 32 : 24">
      <Loading />
    </el-icon>
    <span v-if="text" class="loading-text">{{ text }}</span>
  </div>
</template>

<script lang="ts">
import { Loading } from '@element-plus/icons-vue'
export default { components: { Loading } }
</script>

<style scoped>
.loading-spinner {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 16px;
}

.loading-spinner--small {
  padding: 8px;
}

.loading-spinner--large {
  padding: 24px;
}

.loading-text {
  color: var(--el-text-color-secondary);
  font-size: 14px;
}
</style>
