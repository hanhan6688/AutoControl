import { computed, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  runPCAgentStream,
  resumeAgentRun,
  cancelAgentRun,
  fetchTestPlans,
  fetchTestPlan,
  fetchPCAgentRuns,
  deletePCAgentRun,
  deleteTestPlan,
  deleteImportedTestCase,
  type PCAgentEvent,
  type PCAgentRunRecord,
  type TestPlanListItem,
  type TestPlanProject,
} from '../api'

export interface UsePcAgentRunOptions {
  ensureConnected: () => Promise<boolean>
  onRunStart?: () => void
  onRunComplete: () => Promise<void>
  setUrl: (url: string) => void
  onScreenshot?: (url: string) => void
}

export function usePcAgentRun(
  sessionName: string,
  options: UsePcAgentRunOptions,
  agentProvider?: { provider: () => string; model: () => string | null },
) {
  const currentRunId = ref('')
  const agentTask = ref('检查当前页面是否符合测试要求')
  const agentMaxSteps = ref(8)
  const agentRunning = ref(false)
  const agentNeedUser = ref(false)
  const agentEvents = ref<PCAgentEvent[]>([])
  const lastAgentResult = ref('')
  const needUserReason = ref('')
  const needUserScreenshot = ref('')

  // Test case selector
  const testPlanList = ref<TestPlanListItem[]>([])
  const selectedPlanId = ref<number | null>(null)
  const selectedPlan = ref<TestPlanProject | null>(null)
  const selectedCaseId = ref<number | null>(null)

  let agentController: AbortController | null = null

  const agentStatusText = computed(() => {
    if (agentRunning.value) return 'AI 执行中'
    if (agentNeedUser.value) return '等待人工处理'
    return lastAgentResult.value || '待执行'
  })

  const visibleAgentEvents = computed(() => agentEvents.value.slice(-80))

  function appendAgentEvent(event: PCAgentEvent) {
    agentEvents.value = [...agentEvents.value, event].slice(-200)
    if (event.screenshot_url) {
      options.onScreenshot?.(event.screenshot_url)
    }
    if (event.event === 'start') {
      currentRunId.value = event.run_id || ''
    }
    if (event.event === 'need_user') {
      agentNeedUser.value = true
      lastAgentResult.value = event.message || '等待人工处理'
      needUserReason.value = event.message || '检测到登录页面'
      needUserScreenshot.value = event.screenshot_url || ''
    }
    if (event.event === 'result') {
      agentNeedUser.value = false
      needUserReason.value = ''
      needUserScreenshot.value = ''
      lastAgentResult.value = event.message || String(event.run_result || '执行结束')
    }
    if (event.event === 'error') {
      lastAgentResult.value = event.message || '执行失败'
    }
  }

  function isAbortError(error: unknown) {
    return error instanceof DOMException && error.name === 'AbortError'
  }

  async function runAgentTask(resume = false) {
    const task = agentTask.value.trim()
    if (!task) {
      ElMessage.warning('请先填写 PC 端测试任务')
      return
    }

    const isConnected = await options.ensureConnected()
    if (!isConnected) return

    agentController?.abort()
    agentController = new AbortController()
    agentRunning.value = true
    agentNeedUser.value = false
    currentRunId.value = ''
    needUserReason.value = ''
    needUserScreenshot.value = ''
    if (!resume) {
      agentEvents.value = []
      lastAgentResult.value = ''
    } else {
      appendAgentEvent({
        event: 'log',
        phase: 'manual',
        timestamp: new Date().toISOString(),
        message: '用户已完成手动处理，继续执行 PC Agent。',
      })
    }

    try {
      const finalEvent = await runPCAgentStream(
        {
          task,
          session: sessionName,
          max_steps: agentMaxSteps.value,
          provider: agentProvider?.provider(),
          model: agentProvider?.model(),
        },
        appendAgentEvent,
        agentController.signal,
      )
      if (finalEvent?.event === 'need_user') {
        ElMessage.warning(finalEvent.message || '需要你手动处理后继续')
      } else {
        ElMessage.info(finalEvent?.message || 'PC Agent 执行结束')
      }
      await options.onRunComplete()
    } catch (error) {
      if (isAbortError(error)) {
        appendAgentEvent({
          event: 'error',
          phase: 'agent',
          timestamp: new Date().toISOString(),
          message: 'PC Agent 已停止。',
        })
        ElMessage.warning('已停止 PC Agent')
      } else {
        ElMessage.error(error instanceof Error ? error.message : 'PC Agent 执行失败')
      }
    } finally {
      agentRunning.value = false
      agentController = null
    }
  }

  function stopAgentTask() {
    agentController?.abort()
    agentController = null
    agentRunning.value = false
  }

  async function handleResume() {
    if (!currentRunId.value) return
    try {
      await resumeAgentRun(currentRunId.value)
      needUserReason.value = ''
      needUserScreenshot.value = ''
    } catch (e: any) {
      console.error('恢复执行失败', e)
    }
  }

  async function handleCancel() {
    if (!currentRunId.value) return
    try {
      await cancelAgentRun(currentRunId.value)
      needUserReason.value = ''
      needUserScreenshot.value = ''
      agentRunning.value = false
    } catch (e: any) {
      console.error('取消执行失败', e)
    }
  }

  async function loadTestPlans() {
    try {
      testPlanList.value = await fetchTestPlans()
    } catch { /* ignore */ }
  }

  async function selectTestPlan(planId: number | null) {
    selectedPlanId.value = planId
    selectedCaseId.value = null
    if (!planId) {
      selectedPlan.value = null
      return
    }
    try {
      selectedPlan.value = await fetchTestPlan(planId)
    } catch {
      selectedPlan.value = null
      ElMessage.error('加载测试计划失败')
    }
  }

  function selectTestCase(caseId: number | null) {
    selectedCaseId.value = caseId
    if (!caseId || !selectedPlan.value) return
    const caseItem = selectedPlan.value.cases.find(c => c.id === caseId)
    if (!caseItem) return

    const targetApp = (caseItem.target_app || '').trim()
    if (targetApp.startsWith('http://') || targetApp.startsWith('https://')) {
      options.setUrl(targetApp)
    }

    const stepsText = caseItem.steps.map((step, i) => `步骤${i + 1}: ${step}`).join('\n')
    const expectedText = caseItem.expected_result ? `\n预期结果: ${caseItem.expected_result}` : ''
    const preconditionText = caseItem.precondition ? `前置条件: ${caseItem.precondition}\n\n` : ''
    agentTask.value = preconditionText + stepsText + expectedText
  }

  // ── Run History ──────────────────────────────────────────────────────────────
  const agentRunList = ref<PCAgentRunRecord[]>([])
  const agentRunTotal = ref(0)
  const agentRunPage = ref(1)
  const agentRunListBusy = ref(false)

  async function loadAgentRuns() {
    agentRunListBusy.value = true
    try {
      const data = await fetchPCAgentRuns(agentRunPage.value, 20)
      agentRunList.value = data.items
      agentRunTotal.value = data.total
    } catch (error) {
      console.error('Failed to load agent run history:', error)
    } finally {
      agentRunListBusy.value = false
    }
  }

  async function removeAgentRun(runId: string | number) {
    try {
      await deletePCAgentRun(runId)
      ElMessage.success('已删除运行记录')
      await loadAgentRuns()
    } catch (error) {
      ElMessage.error(error instanceof Error ? error.message : '删除失败')
    }
  }

async function removeTestPlan(planId: number) {
    try {
      await ElMessageBox.confirm(
        '删除测试计划将同时删除其下所有用例和执行记录，确认删除？',
        '删除测试计划',
        { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
      )
    } catch {
      return
    }
    try {
      await deleteTestPlan(planId)
      ElMessage.success('测试计划已删除')
      if (selectedPlanId.value === planId) {
        selectedPlanId.value = null
        selectedPlan.value = null
        selectedCaseId.value = null
      }
      await loadTestPlans()
    } catch (error) {
      ElMessage.error(error instanceof Error ? error.message : '删除测试计划失败')
    }
  }

  async function removeTestCase(caseId: number) {
    try {
      await ElMessageBox.confirm('确认删除该AutoGLM？', '删除AutoGLM', {
        type: 'warning',
        confirmButtonText: '删除',
        cancelButtonText: '取消',
      })
    } catch {
      return
    }
    try {
      await deleteImportedTestCase(caseId)
      ElMessage.success('AutoGLM已删除')
      if (selectedCaseId.value === caseId) {
        selectedCaseId.value = null
      }
      if (selectedPlanId.value) {
        selectedPlan.value = await fetchTestPlan(selectedPlanId.value)
      }
      await loadTestPlans()
    } catch (error) {
      ElMessage.error(error instanceof Error ? error.message : '删除AutoGLM失败')
    }
  }

  return {
    currentRunId,
    agentTask,
    agentMaxSteps,
    agentRunning,
    agentNeedUser,
    agentEvents,
    lastAgentResult,
    needUserReason,
    needUserScreenshot,
    agentStatusText,
    visibleAgentEvents,
    testPlanList,
    selectedPlanId,
    selectedPlan,
    selectedCaseId,
    runAgentTask,
    stopAgentTask,
    handleResume,
    handleCancel,
    loadTestPlans,
    selectTestPlan,
    selectTestCase,
    agentRunList,
    agentRunTotal,
    agentRunPage,
    agentRunListBusy,
    loadAgentRuns,
    removeAgentRun,
    removeTestPlan,
    removeTestCase,
  }
}
