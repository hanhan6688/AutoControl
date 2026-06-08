<script setup lang="ts">
import { Link, VideoPlay, VideoPause } from '@element-plus/icons-vue'

defineProps<{
  url: string
  busy: boolean
  connected: boolean
}>()

const emit = defineEmits<{
  'update:url': [url: string]
  connect: []
  disconnect: []
}>()
</script>

<template>
  <div class="pc-toolbar">
    <el-input
      :model-value="url"
      size="small"
      placeholder="输入浏览器地址"
      :disabled="busy || connected"
      @update:model-value="emit('update:url', $event)"
      @keyup.enter="connected ? null : emit('connect')"
    >
      <template #prefix>
        <el-icon><Link /></el-icon>
      </template>
    </el-input>
    <el-button
      v-if="!connected"
      type="success"
      size="small"
      :loading="busy"
      @click="emit('connect')"
    >
      <el-icon v-if="!busy" class="el-icon--left"><VideoPlay /></el-icon>
      连接
    </el-button>
    <el-button
      v-if="connected"
      type="danger"
      size="small"
      :loading="busy"
      @click="emit('disconnect')"
    >
      <el-icon v-if="!busy" class="el-icon--left"><VideoPause /></el-icon>
      断开
    </el-button>
  </div>
</template>

<style scoped>
.pc-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: var(--el-bg-color);
  border-bottom: 1px solid var(--el-border-color);
}

.pc-toolbar .el-input {
  flex: 1;
}
</style>