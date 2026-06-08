<script setup lang="ts">
defineProps<{
  title?: string
  message?: string
  type?: 'error' | 'warning' | 'info'
}>()

const emit = defineEmits<{
  retry: []
  dismiss: []
}>()
</script>

<template>
  <el-alert
    :title="title || '发生错误'"
    :type="type || 'error'"
    :description="message"
    show-icon
    closable
    @close="emit('dismiss')"
  >
    <template v-if="$slots.default">
      <slot />
    </template>
    <template v-if="$slots.action" #default>
      <slot name="action" />
    </template>
  </el-alert>
</template>
