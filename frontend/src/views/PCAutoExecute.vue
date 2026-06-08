<script setup lang="ts">
import { onBeforeUnmount, onMounted } from 'vue'
import { ElMessageBox } from 'element-plus'
import { usePcBrowser } from '../composables/usePcBrowser'
import { usePcAgentModel } from '../composables/usePcAgentModel'
import { usePcAgentRun } from '../composables/usePcAgentRun'
import { useLeyoujiaAuth } from '../composables/useLeyoujiaAuth'
import {
  PcToolbar,
  PcScreenshotPanel,
  PcModelPanel,
  PcAuthPanel,
  PcAgentPanel,
  PcNeedUserBanner,
  PcPageInfo,
  PcElementsList,
  PcUnifiedLog,
  PcCommandLog,
  PcRunHistory,
} from '../components/pc'

const sessionName = 'pc-autoexecute'

// --- Composables ---
const browser = usePcBrowser(sessionName)

const model = usePcAgentModel()

const agent = usePcAgentRun(
  sessionName,
  {
    ensureConnected: async () => {
      await browser.connectBrowser(true)  // headed for agent monitoring
      return browser.connected.value
    },
    onRunStart: () => {
      browser.startAgentAutoScreenshot(2500)
    },
    onRunComplete: async () => {
      await browser.refreshLogs()
      browser.stopAgentAutoScreenshot()
      await agent.loadAgentRuns()
    },
    setUrl: (newUrl: string) => {
      browser.url.value = newUrl
    },
    onScreenshot: (url: string) => {
      browser.latestScreenshot.value = browser.resolveAssetUrl(url)
    },
  },
  { provider: model.currentProvider, model: model.currentModel },
)

const auth = useLeyoujiaAuth(sessionName, {
  onBrowserConnected: (session) => {
    browser.connected.value = true
    browser.browserTitle.value = session.title
    browser.browserUrl.value = session.url
    browser.url.value = session.url
  },
  startAutoRefresh: () => { browser.startAutoRefresh() },
  stopAutoRefresh: () => { browser.stopAutoRefresh() },
})

// --- Lifecycle ---
onMounted(() => {
  void model.loadModelConfig()
  void auth.loadLeyoujiaStatus('test')
  void auth.loadLeyoujiaStatus('prod')
  void agent.loadTestPlans()
  void agent.loadAgentRuns()
})

onBeforeUnmount(() => {
  agent.stopAgentTask()
  browser.stopAutoRefresh()
  browser.stopAgentAutoScreenshot()
})

function handleLeyoujiaEnvUpdate(env: 'test' | 'prod') {
  auth.leyoujiaAuthEnv.value = env
  void auth.loadLeyoujiaStatus(env)
}

async function handleDisconnect() {
  if (agent.agentRunning.value) {
    try {
      await ElMessageBox.confirm('Agent 正在执行中，断开将取消当前执行。确定要断开吗？', '确认断开', {
        confirmButtonText: '断开',
        cancelButtonText: '取消',
        type: 'warning',
      })
    } catch {
      return
    }
    agent.stopAgentTask()
  }
  await browser.disconnectBrowser()
}

function openReportUrl(url: string) {
  window.open(url, '_blank')
}

</script>

<template>
  <div class="pc-page">
    <PcToolbar
      :url="browser.url.value"
      :busy="browser.busy.value"
      :connected="browser.connected.value"
      @update:url="browser.url.value = $event"
      @connect="browser.connectBrowser()"
      @disconnect="handleDisconnect()"
    />

    <main class="pc-layout">
      <section class="screenshot-section">
        <PcScreenshotPanel
          :latest-screenshot="browser.latestScreenshot.value"
          :connected="browser.connected.value"
          :pc-recording-enabled="browser.pcRecordingEnabled.value"
          :pc-generated-code="browser.pcGeneratedCode.value"
          :pc-selected-element="browser.pcSelectedElement.value"
          :screenshot-click-enabled="browser.screenshotClickEnabled.value"
          :auto-refresh-active="browser.autoRefreshActive.value"
          :quick-action-busy="browser.quickActionBusy.value"
          @screenshot-click="browser.handleScreenshotClick($event)"
          @toggle-recording="browser.togglePcRecording()"
          @capture-screenshot="browser.captureStepScreenshot()"
          @refresh-snapshot="browser.refreshSnapshot()"
          @click-element="browser.clickSelectedElement()"
          @toggle-auto-refresh="browser.toggleAutoRefresh()"
          @find-and-click="browser.findAndClick($event)"
          @find-and-fill="(label: string, text: string) => browser.findAndFill(label, text)"
          @press-key="browser.pressKey($event)"
          @scroll-page="(dir: string, amt: number) => browser.scrollPage(dir, amt)"
          @preview="browser.previewScreenshot.value = $event"
        />
      </section>

      <aside class="control-panel">
        <PcModelPanel
          :model-config="model.modelConfig.value"
          :model-presets="model.modelPresets.value"
          :model-form="model.modelForm"
          :model-busy="model.modelBusy.value"
          :model-testing="model.modelTesting.value"
          :current-model-label="model.currentModelLabel.value"
          :api-key-placeholder="model.apiKeyPlaceholder.value"
          @apply-preset="model.applyPreset($event)"
          @save="model.saveModelConfig()"
          @test="model.testModelConfig()"
        />

        <PcAuthPanel
          :leyoujia-auth-env="auth.leyoujiaAuthEnv.value"
          :leyoujia-auth-busy="auth.leyoujiaAuthBusy.value"
          :login-polling-active="auth.loginPollingActive.value"
          :current-leyoujia-auth-status="auth.currentLeyoujiaAuthStatus.value"
          :leyoujia-auth-saved="auth.leyoujiaAuthSaved.value"
          :leyoujia-auth-status-text="auth.leyoujiaAuthStatusText.value"
          :leyoujia-login-button-text="auth.leyoujiaLoginButtonText.value"
          :connected="browser.connected.value"
          @update:env="handleLeyoujiaEnvUpdate"
          @open-login="auth.openLeyoujiaLoginPage()"
          @save-state="auth.saveLeyoujiaLoginState()"
          @load-state="auth.loadLeyoujiaLoginState()"
        />

        <PcAgentPanel
          :agent-task="agent.agentTask.value"
          :agent-max-steps="agent.agentMaxSteps.value"
          :agent-running="agent.agentRunning.value"
          :agent-need-user="agent.agentNeedUser.value"
          :agent-status-text="agent.agentStatusText.value"
          :selected-plan-id="agent.selectedPlanId.value"
          :selected-plan="agent.selectedPlan.value"
          :selected-case-id="agent.selectedCaseId.value"
          :test-plan-list="agent.testPlanList.value"
          @update:agent-task="agent.agentTask.value = $event"
          @update:agent-max-steps="agent.agentMaxSteps.value = $event"
          @update:selected-plan-id="agent.selectTestPlan($event)"
          @update:selected-case-id="agent.selectTestCase($event)"
          @run="agent.runAgentTask($event)"
          @stop="agent.stopAgentTask()"
          @delete-plan="agent.removeTestPlan($event)"
          @delete-case="agent.removeTestCase($event)"
        />

        <PcNeedUserBanner
          v-if="agent.needUserReason.value"
          :need-user-reason="agent.needUserReason.value"
          :need-user-screenshot="browser.resolveAssetUrl(agent.needUserScreenshot.value)"
          @resume="agent.handleResume()"
          @cancel="agent.handleCancel()"
        />

        <PcPageInfo
          :browser-url="browser.browserUrl.value"
          :browser-title="browser.browserTitle.value"
        />

        <PcElementsList
          :elements="browser.elements.value"
          @click="browser.clickElement($event)"
          @fill="(ref: string, text: string) => browser.fillElement(ref, text)"
          @hover="browser.hoverElement($event)"
        />

        <PcUnifiedLog
          :events="agent.visibleAgentEvents.value"
          @preview="browser.previewScreenshot.value = $event"
        />

        <PcCommandLog
          :logs="browser.logs.value"
        />

        <PcRunHistory
          :runs="agent.agentRunList.value"
          :total="agent.agentRunTotal.value"
          :busy="agent.agentRunListBusy.value"
          @load="agent.loadAgentRuns()"
          @delete="agent.removeAgentRun($event)"
          @open="openReportUrl"
        />
      </aside>
    </main>

    <!-- Screenshot preview overlay -->
    <div v-if="browser.previewScreenshot.value" class="screenshot-overlay" @click="browser.previewScreenshot.value = ''">
      <img :src="browser.resolveAssetUrl(browser.previewScreenshot.value)" alt="截图预览" />
    </div>
  </div>
</template>

<style scoped>
.pc-page {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  background: var(--bg-primary);
}

.pc-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 360px;
  flex: 1;
  min-height: 0;
}

.screenshot-section {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  padding: 12px;
}

.control-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 12px;
  border-left: 1px solid var(--border-color);
  background: var(--bg-secondary);
  overflow: auto;
}

.screenshot-overlay {
  position: fixed;
  top: 0;
  left: 0;
  width: 100vw;
  height: 100vh;
  background: rgba(0, 0, 0, 0.8);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9999;
  cursor: pointer;
}

.screenshot-overlay img {
  max-width: 90vw;
  max-height: 90vh;
  border-radius: 4px;
}
</style>