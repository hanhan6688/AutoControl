<script setup lang="ts">
defineProps<{
  logs: any[]
}>()
</script>

<template>
  <section class="panel-section command-log">
    <div class="section-title">命令日志</div>
    <div v-if="logs?.length" class="log-items">
      <div
        v-for="(log, idx) in logs"
        :key="idx"
        class="log-item"
      >
        <el-tag
          :type="log.ok === false || log.level === 'error' ? 'danger' : log.level === 'warn' ? 'warning' : 'info'"
          size="small"
        >
          {{ log.ok === false ? 'error' : log.level || 'info' }}
        </el-tag>
        <span class="log-time">{{ log.timestamp || log.time || '' }}</span>
        <span class="log-text">{{ log.stderr || log.stdout || log.message || log.text || log.content || '' }}</span>
      </div>
    </div>
    <el-empty v-else description="暂无命令日志" :image-size="40" />
  </section>
</template>

<style scoped>
.panel-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.command-log {
  padding-bottom: 10px;
  border-bottom: 1px solid var(--border-color);
}

.section-title {
  color: var(--text-primary);
  font-size: 12px;
  font-weight: 700;
}

.log-items {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 200px;
  overflow: auto;
}

.log-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 6px;
  border-radius: 4px;
  background: var(--bg-primary);
  font-size: 12px;
}

.log-time {
  color: var(--text-muted);
  font-size: 11px;
  white-space: nowrap;
}

.log-text {
  color: var(--text-primary);
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}
</style>
