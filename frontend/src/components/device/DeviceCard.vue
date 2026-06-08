<script setup lang="ts">
import { Cellphone } from '@element-plus/icons-vue'
import type { DeviceInfo } from '../../api'
import DeviceStatusBadge from './DeviceStatusBadge.vue'

defineProps<{
  device: DeviceInfo
  active?: boolean
}>()

const emit = defineEmits<{
  click: [device: DeviceInfo]
  connect: [device: DeviceInfo]
}>()
</script>

<template>
  <el-card
    class="device-card"
    :class="{ 'device-card--active': active }"
    shadow="hover"
    @click="emit('click', device)"
  >
    <div class="device-card__content">
      <div class="device-card__icon">
        <el-icon :size="32">
          <Cellphone />
        </el-icon>
      </div>
      <div class="device-card__info">
        <div class="device-card__name">
          {{ device.model || device.udid }}
        </div>
        <div class="device-card__meta">
          <DeviceStatusBadge :status="device.status" />
          <span class="device-card__platform">{{ device.platform }}</span>
          <span v-if="device.os_version" class="device-card__os">
            {{ device.os_version }}
          </span>
        </div>
      </div>
      <div v-if="device.status === 'online'" class="device-card__action">
        <el-button
          type="primary"
          size="small"
          @click.stop="emit('connect', device)"
        >
          投屏
        </el-button>
      </div>
    </div>
  </el-card>
</template>

<style scoped>
.device-card {
  cursor: pointer;
  transition: all 0.2s ease;
}

.device-card:hover {
  border-color: var(--el-color-primary);
}

.device-card--active {
  border-color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
}

.device-card__content {
  display: flex;
  align-items: center;
  gap: 12px;
}

.device-card__icon {
  color: var(--el-text-color-secondary);
}

.device-card__info {
  flex: 1;
  min-width: 0;
}

.device-card__name {
  font-weight: 500;
  font-size: 14px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.device-card__meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 4px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.device-card__platform {
  text-transform: capitalize;
}
</style>
