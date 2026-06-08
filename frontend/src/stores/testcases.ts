import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import {
  fetchTestPlans,
  fetchTestPlan,
  importTestPlan,
  runImportedTestCase,
  runImportedTestPlan,
  type TestPlanListItem,
  type TestPlanProject,
  type TestCaseExecution,
} from '../api'

export const useTestCaseStore = defineStore('testcases', () => {
  const testPlans = ref<TestPlanListItem[]>([])
  const selectedPlan = ref<TestPlanProject | null>(null)
  const loading = ref(false)
  const importing = ref(false)
  const running = ref(false)
  const runningCaseId = ref<number | null>(null)
  const error = ref<string | null>(null)

  const totalCases = computed(() =>
    testPlans.value.reduce((sum, p) => sum + p.total_cases, 0)
  )

  async function loadTestPlans() {
    loading.value = true
    error.value = null
    try {
      testPlans.value = await fetchTestPlans()
      if (testPlans.value.length && !selectedPlan.value) {
        await selectPlan(testPlans.value[0].id)
      }
    } catch (e) {
      error.value = e instanceof Error ? e.message : '获取测试计划失败'
    } finally {
      loading.value = false
    }
  }

  async function selectPlan(planId: number) {
    loading.value = true
    error.value = null
    try {
      selectedPlan.value = await fetchTestPlan(planId)
    } catch (e) {
      error.value = e instanceof Error ? e.message : '获取测试计划详情失败'
    } finally {
      loading.value = false
    }
  }

  async function importNewPlan(file: File, projectName: string) {
    importing.value = true
    error.value = null
    try {
      const plan = await importTestPlan(file, projectName)
      testPlans.value.push({
        id: plan.id,
        name: plan.name,
        source_filename: plan.source_filename,
        total_cases: plan.total_cases,
        imported_at: plan.imported_at,
      })
      selectedPlan.value = plan
      return plan
    } catch (e) {
      error.value = e instanceof Error ? e.message : '导入测试计划失败'
      return null
    } finally {
      importing.value = false
    }
  }

  async function runCase(caseId: number, deviceUdid?: string) {
    runningCaseId.value = caseId
    error.value = null
    try {
      const execution = await runImportedTestCase(caseId, deviceUdid)
      // Refresh plan to get updated results
      if (selectedPlan.value) {
        await selectPlan(selectedPlan.value.id)
      }
      return execution
    } catch (e) {
      error.value = e instanceof Error ? e.message : '执行用例失败'
      return null
    } finally {
      runningCaseId.value = null
    }
  }

  async function runAllCases(planId: number, deviceUdid?: string) {
    running.value = true
    error.value = null
    try {
      const result = await runImportedTestPlan(planId, deviceUdid)
      if (selectedPlan.value?.id === planId) {
        await selectPlan(planId)
      }
      return result
    } catch (e) {
      error.value = e instanceof Error ? e.message : '批量执行失败'
      return null
    } finally {
      running.value = false
    }
  }

  return {
    testPlans,
    selectedPlan,
    loading,
    importing,
    running,
    runningCaseId,
    error,
    totalCases,
    loadTestPlans,
    selectPlan,
    importNewPlan,
    runCase,
    runAllCases,
  }
})
