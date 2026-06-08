<script setup lang="ts">
import {
  Back,
  HomeFilled,
  Grid,
  Camera,
  Refresh,
  VideoPlay,
  VideoPause,
} from '@element-plus/icons-vue'

defineProps<{
  isConnected: boolean
  canGoBack?: boolean
}>()

const emit = defineEmits<{
  back: []
  home: []
  appSwitch: []
  screenshot: []
  refresh: []
  toggleConnection: []
}>()
</script>

<template>
  <div class="screen-toolbar">
    <el-button-group>
      <el-tooltip content="返回" placement="top">
        <el-button :icon="Back" size="small" @click="emit('back')" />
      </el-tooltip>
      <el-tooltip content="主页" placement="top">
        <el-button :icon="HomeFilled" size="small" @click="emit('home')" />
      </el-tooltip>
      <el-tooltip content="应用切换" placement="top">
        <el-button :icon="Grid" size="small" @click="emit('appSwitch')" />
      </el-tooltip>
    </el-button-group>

    <el-button-group>
      <el-tooltip content="截图" placement="top">
        <el-button :icon="Camera" size="small" @click="emit('screenshot')" />
      </el-tooltip>
      <el-tooltip content="刷新" placement="top">
        <el-button :icon="Refresh" size="small" @click="emit('refresh')" />
      </el-tooltip>
    </el-button-group>

    <el-button
      :type="isConnected ? 'danger' : 'success'"
      size="small"
      @click="emit('toggleConnection')"
    >
      <el-icon class="el-icon--left">
        <VideoPause v-if="isConnected" />
        <VideoPlay v-else />
      </el-icon>
      {{ isConnected ? '断开' : '连接' }}
    </el-button>
  </div>
</template>

<style scoped>
.screen-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 12px;
  background: var(--el-bg-color);
  border-bottom: 1px solid var(--el-border-color);
}
</style>
