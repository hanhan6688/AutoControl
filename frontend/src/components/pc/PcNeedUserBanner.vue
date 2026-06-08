<script setup lang="ts">
import { VideoPlay, CircleClose } from '@element-plus/icons-vue'

defineProps<{
  needUserReason: string
  needUserScreenshot: string
}>()

const emit = defineEmits<{
  resume: []
  cancel: []
}>()
</script>

<template>
  <el-alert
    type="warning"
    show-icon
    :closable="false"
    class="need-user-banner"
  >
    <template #title>
      <span>需要人工干预</span>
    </template>
    <template #default>
      <div class="banner-content">
        <p class="reason-text">{{ needUserReason }}</p>
        <div v-if="needUserScreenshot" class="banner-screenshot">
          <img :src="needUserScreenshot" alt="需要人工干预截图" @click="emit('resume')" />
        </div>
        <div class="banner-actions">
          <el-button
            :icon="VideoPlay"
            size="small"
            type="warning"
            @click="emit('resume')"
          >
            继续
          </el-button>
          <el-button
            :icon="CircleClose"
            size="small"
            @click="emit('cancel')"
          >
            取消
          </el-button>
        </div>
      </div>
    </template>
  </el-alert>
</template>

<style scoped>
.need-user-banner {
  margin: 0;
}

.banner-content {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.reason-text {
  margin: 0;
  font-size: 12px;
  color: var(--text-primary);
}

.banner-screenshot {
  max-width: 200px;
}

.banner-screenshot img {
  width: 100%;
  border-radius: 4px;
  cursor: pointer;
}

.banner-actions {
  display: flex;
  gap: 6px;
}
</style>
