<script setup lang="ts">
defineProps<{
  status: 'online' | 'offline' | 'unauthorized' | 'unknown'
}>()

const statusConfig: Record<string, { type: string; label: string }> = {
  online: { type: 'success', label: '在线' },
  offline: { type: 'info', label: '离线' },
  unauthorized: { type: 'warning', label: '未授权' },
  unknown: { type: 'danger', label: '未知' },
}
</script>

<template>
  <el-tag :type="statusConfig[status]?.type as any" size="small">
    {{ statusConfig[status]?.label || status }}
  </el-tag>
</template>
