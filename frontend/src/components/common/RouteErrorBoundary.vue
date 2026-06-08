<script setup lang="ts">
import { computed, onErrorCaptured, shallowRef, watch } from 'vue'
import { RefreshRight } from '@element-plus/icons-vue'

const props = defineProps<{
  resetKey: string
}>()

const emit = defineEmits<{
  retry: []
}>()

const capturedError = shallowRef<unknown>(null)

const errorMessage = computed(() => {
  const error = capturedError.value
  if (error instanceof Error) return error.message
  return String(error || '模块加载失败')
})

onErrorCaptured((error) => {
  capturedError.value = error
  console.error('[Route error]', error)
  return false
})

watch(
  () => props.resetKey,
  () => {
    capturedError.value = null
  },
)

function retry() {
  capturedError.value = null
  emit('retry')
}
</script>

<template>
  <slot v-if="!capturedError" />
  <section v-else class="route-error">
    <div class="route-error-panel">
      <div class="route-error-title">当前模块加载失败</div>
      <div class="route-error-message">{{ errorMessage }}</div>
      <el-button type="primary" :icon="RefreshRight" @click="retry">
        重新加载模块
      </el-button>
    </div>
  </section>
</template>

<style scoped>
.route-error {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100%;
  padding: 32px;
  background: var(--bg-primary);
}

.route-error-panel {
  width: min(520px, 100%);
  padding: 24px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--bg-secondary);
}

.route-error-title {
  margin-bottom: 8px;
  color: var(--text-primary);
  font-size: 16px;
  font-weight: 700;
}

.route-error-message {
  margin-bottom: 18px;
  color: var(--text-secondary);
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 12px;
  line-height: 1.5;
  overflow-wrap: anywhere;
}
</style>
