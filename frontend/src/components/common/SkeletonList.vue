<script setup lang="ts">
defineProps<{
  rows?: number
  avatar?: boolean
  compact?: boolean
}>()
</script>

<template>
  <div class="skeleton-list">
    <div v-if="avatar" class="skeleton-avatar-row">
      <div class="skeleton-avatar"></div>
      <div class="skeleton-lines">
        <div class="skeleton-line short"></div>
        <div class="skeleton-line medium"></div>
      </div>
    </div>
    <div
      v-for="i in rows || 3"
      :key="i"
      class="skeleton-row"
      :class="{ compact }"
    >
      <div class="skeleton-line"></div>
      <div class="skeleton-line short"></div>
    </div>
  </div>
</template>

<style scoped>
.skeleton-list {
  padding: 8px 0;
}

.skeleton-avatar-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 0;
}

.skeleton-avatar {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  background: linear-gradient(90deg, #f0f0f0 25%, #e0e0e0 50%, #f0f0f0 75%);
  background-size: 200% 100%;
  animation: skeleton-pulse 1.5s ease-in-out infinite;
}

.skeleton-lines {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.skeleton-row {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 12px 0;
}

.skeleton-row.compact {
  padding: 8px 0;
}

.skeleton-line {
  height: 14px;
  border-radius: 4px;
  background: linear-gradient(90deg, #f0f0f0 25%, #e0e0e0 50%, #f0f0f0 75%);
  background-size: 200% 100%;
  animation: skeleton-pulse 1.5s ease-in-out infinite;
  flex: 1;
}

.skeleton-line.short {
  width: 60px;
  flex: none;
}

.skeleton-line.medium {
  width: 120px;
  flex: none;
}

@keyframes skeleton-pulse {
  0% {
    background-position: 200% 0;
  }
  100% {
    background-position: -200% 0;
  }
}
</style>