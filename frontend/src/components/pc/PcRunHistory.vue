<script setup lang="ts">
import { Refresh, Delete, View } from '@element-plus/icons-vue'

defineProps<{
  runs: any[]
  total: number
  busy: boolean
}>()

const emit = defineEmits<{
  load: []
  delete: [id: number]
  open: [url: string]
}>()
</script>

<template>
  <section class="panel-section run-history">
    <div class="section-title">
      执行历史
      <span v-if="total" class="total-badge">({{ total }})</span>
    </div>

    <el-button
      :icon="Refresh"
      size="small"
      :loading="busy"
      @click="emit('load')"
    >
      刷新
    </el-button>

    <div v-if="runs?.length" class="run-items">
      <div
        v-for="run in runs"
        :key="run.id"
        class="run-item"
      >
        <div class="run-info">
          <el-tag
            :type="run.run_result === 'passed' ? 'success' : run.run_result === 'failed' ? 'danger' : run.run_result === 'running' ? 'warning' : run.run_result === 'need_user' ? 'warning' : 'info'"
            size="small"
          >
            {{ run.run_result === 'passed' ? '通过' : run.run_result === 'failed' ? '失败' : run.run_result === 'running' ? '执行中' : run.run_result === 'need_user' ? '需人工' : run.run_result === 'cancelled' ? '已取消' : run.run_result || '未知' }}
          </el-tag>
          <span class="run-name">{{ run.task || `执行 #${run.id}` }}</span>
        </div>
        <div class="run-actions">
          <el-tooltip content="查看报告" placement="top">
            <el-button
              v-if="run.report_url || run.reportUrl"
              :icon="View"
              size="small"
              @click="emit('open', run.report_url || run.reportUrl)"
            />
          </el-tooltip>
          <el-tooltip content="删除" placement="top">
            <el-button
              :icon="Delete"
              size="small"
              type="danger"
              plain
              @click="emit('delete', run.id)"
            />
          </el-tooltip>
        </div>
      </div>
    </div>
    <el-empty v-else description="暂无执行历史" :image-size="40" />
  </section>
</template>

<style scoped>
.panel-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.run-history {
  padding-bottom: 10px;
  border-bottom: 1px solid var(--border-color);
}

.section-title {
  color: var(--text-primary);
  font-size: 12px;
  font-weight: 700;
}

.total-badge {
  color: var(--text-muted);
  font-weight: 400;
  font-size: 11px;
}

.run-items {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 200px;
  overflow: auto;
}

.run-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 6px;
  border-radius: 4px;
  background: var(--bg-primary);
}

.run-info {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  flex: 1;
}

.run-name {
  font-size: 12px;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.run-actions {
  display: flex;
  gap: 2px;
  flex-shrink: 0;
}
</style>
