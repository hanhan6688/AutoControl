<script setup lang="ts">
import { VideoPlay, CircleClose, Delete } from '@element-plus/icons-vue'
import type { TestPlanListItem, TestPlanProject } from '../../api'

defineProps<{
  agentTask: string
  agentMaxSteps: number
  agentRunning: boolean
  agentNeedUser: boolean
  agentStatusText: string
  selectedPlanId: number | null
  selectedPlan: TestPlanProject | null
  selectedCaseId: number | null
  testPlanList: TestPlanListItem[]
}>()

const emit = defineEmits<{
  'update:agentTask': [task: string]
  'update:agentMaxSteps': [steps: number]
  'update:selectedPlanId': [planId: number | null]
  'update:selectedCaseId': [caseId: number | null]
  run: [resume: boolean]
  stop: []
  deletePlan: [planId: number]
  deleteCase: [caseId: number]
}>()
</script>

<template>
  <section class="panel-section agent-panel">
    <div class="section-title">AI 执行</div>
    <div class="agent-status" :class="{ waiting: agentNeedUser, running: agentRunning }">
      {{ agentStatusText }}
    </div>
    <div class="case-selector">
      <el-select
        :model-value="selectedPlanId"
        size="small"
        placeholder="选择测试计划"
        clearable
        @update:model-value="emit('update:selectedPlanId', $event as number | null)"
      >
        <el-option
          v-for="plan in testPlanList"
          :key="plan.id"
          :label="plan.name"
          :value="plan.id"
        />
      </el-select>
      <el-button
        v-if="selectedPlanId"
        :icon="Delete"
        size="small"
        type="danger"
        plain
        @click="emit('deletePlan', selectedPlanId)"
      />
      <el-select
        :model-value="selectedCaseId"
        size="small"
        placeholder="选择AutoGLM"
        clearable
        :disabled="!selectedPlan"
        @update:model-value="emit('update:selectedCaseId', $event as number | null)"
      >
        <el-option
          v-for="caseItem in selectedPlan?.cases || []"
          :key="caseItem.id"
          :label="caseItem.case_name"
          :value="caseItem.id"
        />
      </el-select>
      <el-button
        v-if="selectedCaseId"
        :icon="Delete"
        size="small"
        type="danger"
        plain
        @click="emit('deleteCase', selectedCaseId)"
      />
    </div>
    <el-input
      :model-value="agentTask"
      type="textarea"
      :rows="4"
      resize="none"
      placeholder="输入 PC 端测试任务，例如：登录后进入后台并检查首页标题"
      @update:model-value="emit('update:agentTask', $event)"
    />
    <div class="agent-row">
      <el-input-number :model-value="agentMaxSteps" size="small" :min="1" :max="30" controls-position="right" @update:model-value="emit('update:agentMaxSteps', $event)" />
      <el-button
        :icon="VideoPlay"
        type="primary"
        size="small"
        :loading="agentRunning"
        :disabled="agentRunning"
        @click="emit('run', false)"
      >
        执行
      </el-button>
      <el-button
        v-if="agentNeedUser"
        size="small"
        type="warning"
        :disabled="agentRunning"
        @click="emit('run', true)"
      >
        继续
      </el-button>
      <el-button
        :icon="CircleClose"
        size="small"
        :disabled="!agentRunning"
        @click="emit('stop')"
      >
        停止
      </el-button>
    </div>
    <el-alert
      v-if="agentNeedUser"
      class="manual-alert"
      type="warning"
      show-icon
      :closable="false"
      title="检测到需要人工处理的步骤，请在浏览器中完成后点击继续"
    />
  </section>
</template>

<style scoped>
.panel-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.agent-panel {
  padding-bottom: 10px;
  border-bottom: 1px solid var(--border-color);
}

.section-title {
  color: var(--text-primary);
  font-size: 12px;
  font-weight: 700;
}

.agent-status {
  align-self: flex-start;
  padding: 3px 8px;
  border-radius: 4px;
  background: var(--bg-primary);
  color: var(--text-muted);
  font-size: 12px;
}

.agent-status.running {
  color: var(--primary);
}

.agent-status.waiting {
  color: var(--warning);
}

.case-selector {
  display: flex;
  gap: 8px;
  margin-bottom: 8px;
}

.case-selector .el-select {
  flex: 1;
}

.agent-row {
  display: grid;
  grid-template-columns: 86px repeat(3, auto);
  gap: 6px;
  align-items: center;
}

.manual-alert {
  margin-top: 2px;
}
</style>