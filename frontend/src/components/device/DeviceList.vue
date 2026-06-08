<script setup lang="ts">
import { ref } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import type { DeviceInfo } from '../../api'
import DeviceCard from './DeviceCard.vue'
import { LoadingSpinner, EmptyState } from '../common'

defineProps<{
  devices: DeviceInfo[]
  activeDevice: DeviceInfo | null
  loading: boolean
}>()

const emit = defineEmits<{
  refresh: []
  select: [device: DeviceInfo]
  connect: [device: DeviceInfo]
}>()

const searchQuery = ref('')
</script>

<template>
  <div class="device-list">
    <div class="device-list__header">
      <el-input
        v-model="searchQuery"
        placeholder="搜索设备..."
        clearable
        style="width: 200px"
      />
      <el-button :icon="Refresh" @click="emit('refresh')">刷新</el-button>
    </div>

    <LoadingSpinner v-if="loading" text="加载设备中..." />

    <EmptyState
      v-else-if="!devices.length"
      title="未检测到设备"
      description="请连接 Android 设备并开启 USB 调试"
    >
      <el-button type="primary" @click="emit('refresh')">
        刷新设备列表
      </el-button>
    </EmptyState>

    <div v-else class="device-list__grid">
      <DeviceCard
        v-for="device in devices"
        :key="device.udid"
        :device="device"
        :active="activeDevice?.udid === device.udid"
        @click="emit('select', device)"
        @connect="emit('connect', device)"
      />
    </div>
  </div>
</template>

<style scoped>
.device-list {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.device-list__header {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
}

.device-list__grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 12px;
  overflow-y: auto;
}
</style>
