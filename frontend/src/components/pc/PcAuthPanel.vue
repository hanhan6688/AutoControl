<script setup lang="ts">
import { Switch, Upload, Download, User } from '@element-plus/icons-vue'

defineProps<{
  leyoujiaAuthEnv: 'test' | 'prod'
  leyoujiaAuthBusy: boolean
  loginPollingActive: boolean
  currentLeyoujiaAuthStatus: any
  leyoujiaAuthSaved: boolean
  leyoujiaAuthStatusText: string
  leyoujiaLoginButtonText: string
  connected: boolean
}>()

const emit = defineEmits<{
  'update:env': [env: 'test' | 'prod']
  'open-login': []
  'save-state': []
  'load-state': []
}>()
</script>

<template>
  <section class="panel-section auth-panel">
    <div class="section-title">乐有家认证</div>

    <div class="env-switch">
      <span class="info-label">环境:</span>
      <el-radio-group
        :model-value="leyoujiaAuthEnv"
        size="small"
        @update:model-value="emit('update:env', $event as 'test' | 'prod')"
      >
        <el-radio-button value="test">测试</el-radio-button>
        <el-radio-button value="prod">生产</el-radio-button>
      </el-radio-group>
    </div>

    <div class="auth-status">
      <span class="info-label">状态:</span>
      <el-tag
        size="small"
        :type="leyoujiaAuthSaved ? 'success' : 'info'"
      >
        {{ leyoujiaAuthStatusText || '未认证' }}
      </el-tag>
    </div>

    <div class="auth-actions">
      <el-button
        :icon="User"
        size="small"
        type="primary"
        :loading="leyoujiaAuthBusy || loginPollingActive"
        :disabled="!connected"
        @click="emit('open-login')"
      >
        {{ leyoujiaLoginButtonText || '登录' }}
      </el-button>
      <el-button
        :icon="Upload"
        size="small"
        :disabled="!leyoujiaAuthSaved"
        @click="emit('save-state')"
      >
        保存
      </el-button>
      <el-button
        :icon="Download"
        size="small"
        @click="emit('load-state')"
      >
        加载
      </el-button>
    </div>
  </section>
</template>

<style scoped>
.panel-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.auth-panel {
  padding-bottom: 10px;
  border-bottom: 1px solid var(--border-color);
}

.section-title {
  color: var(--text-primary);
  font-size: 12px;
  font-weight: 700;
}

.info-label {
  color: var(--text-muted);
  font-size: 12px;
}

.env-switch {
  display: flex;
  align-items: center;
  gap: 6px;
}

.auth-status {
  display: flex;
  align-items: center;
  gap: 6px;
}

.auth-actions {
  display: flex;
  gap: 6px;
}
</style>
