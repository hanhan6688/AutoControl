import { computed, reactive, shallowRef } from 'vue'
import type { TestCaseRunStreamEvent } from '../api'

const PHASE_ORDER = ['device_check', 'precondition', 'execution', 'report'] as const

export function useCaseRunLogs() {
  const caseRunLogs = reactive<Record<number, TestCaseRunStreamEvent[]>>({})
  const runningCaseIds = reactive<Record<number, boolean>>({})
  const runningCaseId = shallowRef<number | null>(null)

  const hasRunningCase = computed(() => Object.values(runningCaseIds).some(Boolean))

  function startCaseLog(caseId: number) {
    caseRunLogs[caseId] = []
    runningCaseIds[caseId] = true
    runningCaseId.value = caseId
  }

  function appendCaseLog(caseId: number, event: TestCaseRunStreamEvent) {
    if (!caseRunLogs[caseId]) {
      caseRunLogs[caseId] = []
    }
    caseRunLogs[caseId].push(event)
  }

  function finishCaseLog(caseId: number) {
    runningCaseIds[caseId] = false
    const nextRunningId = Number(Object.entries(runningCaseIds).find(([, running]) => running)?.[0])
    runningCaseId.value = Number.isFinite(nextRunningId) ? nextRunningId : null
  }

  function isCaseRunning(caseId: number): boolean {
    return Boolean(runningCaseIds[caseId])
  }

  function getCaseLogs(caseId: number): TestCaseRunStreamEvent[] {
    return caseRunLogs[caseId] ?? []
  }

  function getCasePhaseLogs(caseId: number, phase: string): TestCaseRunStreamEvent[] {
    return getCaseLogs(caseId).filter(event => event.phase === phase)
  }

  function getVisiblePhases(caseId: number): string[] {
    const logs = getCaseLogs(caseId)
    return PHASE_ORDER.filter(phase => logs.some(event => event.phase === phase))
  }

  function isCaseWaitingForUser(caseId: number): boolean {
    const logs = getCaseLogs(caseId)
    if (!logs.length) return false
    const lastEvent = logs[logs.length - 1]
    return lastEvent.event === 'need_user'
  }

  function finishAllCaseLogs() {
    for (const caseId of Object.keys(runningCaseIds)) {
      runningCaseIds[Number(caseId)] = false
    }
    runningCaseId.value = null
  }

  return {
    caseRunLogs,
    runningCaseIds,
    runningCaseId,
    hasRunningCase,
    startCaseLog,
    appendCaseLog,
    finishCaseLog,
    finishAllCaseLogs,
    isCaseRunning,
    isCaseWaitingForUser,
    getCaseLogs,
    getCasePhaseLogs,
    getVisiblePhases,
  }
}
