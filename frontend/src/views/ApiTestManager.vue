<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Delete, Edit, Plus, Refresh, VideoPlay } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  fetchApiTestSuites, createApiTestSuite, fetchApiTestSuite, updateApiTestSuite, deleteApiTestSuite,
  createApiTestCase, updateApiTestCase, deleteApiTestCase, runApiTestCase, runApiTestSuite,
  type ApiTestSuite, type ApiTestCase, type ApiTestExecution, type ApiTestSuiteRunResponse,
} from '../api'

const suites = ref<ApiTestSuite[]>([])
const selectedSuite = ref<ApiTestSuite | null>(null)
const suitesLoading = ref(false)
const suiteDetailLoading = ref(false)

const suiteDialogVisible = ref(false)
const suiteDialogBusy = ref(false)
const isEditingSuite = ref(false)

interface SuiteForm {
  id: number | null
  name: string
  base_url: string
  auth_type: string
  auth_config_token: string
  auth_config_username: string
  auth_config_password: string
}

const suiteForm = ref<SuiteForm>({
  id: null,
  name: '',
  base_url: '',
  auth_type: 'none',
  auth_config_token: '',
  auth_config_username: '',
  auth_config_password: '',
})

const caseDialogVisible = ref(false)
const caseDialogBusy = ref(false)
const isEditingCase = ref(false)

interface KvPair {
  key: string
  value: string
}

interface CaseForm {
  id: number | null
  name: string
  method: string
  path: string
  headers: KvPair[]
  params: KvPair[]
  bodyText: string
  expected_status: number
  expected_body_contains: string
  expected_schema: string
  extract_vars: KvPair[]
  tags: string
  priority: string
}

const caseForm = ref<CaseForm>({
  id: null,
  name: '',
  method: 'GET',
  path: '',
  headers: [],
  params: [],
  bodyText: '',
  expected_status: 200,
  expected_body_contains: '',
  expected_schema: '',
  extract_vars: [],
  tags: '',
  priority: 'P1',
})

const runningCaseIds = ref<Set<number>>(new Set())
const runningSuiteId = ref<number | null>(null)

const resultDrawerVisible = ref(false)
const currentExecution = ref<ApiTestExecution | null>(null)

const methodTypeMap: Record<string, string> = {
  GET: 'success',
  POST: 'warning',
  PUT: 'info',
  DELETE: 'danger',
  PATCH: '',
}

function methodType(method: string) {
  return methodTypeMap[method] ?? ''
}

function resultType(result: string) {
  if (result === 'passed') return 'success'
  if (result === 'failed') return 'danger'
  return 'info'
}

function resultLabel(result: string) {
  if (result === 'passed') return '通过'
  if (result === 'failed') return '失败'
  if (result === 'pending') return '待执行'
  return result || '待执行'
}

function kvToRecord(pairs: KvPair[]): Record<string, string> {
  const record: Record<string, string> = {}
  for (const p of pairs) {
    if (p.key.trim()) record[p.key.trim()] = p.value
  }
  return record
}

function recordToKv(record: Record<string, string> | null | undefined): KvPair[] {
  if (!record) return []
  return Object.entries(record).map(([key, value]) => ({ key, value }))
}

function addKvPair(list: KvPair[]) {
  list.push({ key: '', value: '' })
}

function removeKvPair(list: KvPair[], index: number) {
  list.splice(index, 1)
}

function resetSuiteForm() {
  suiteForm.value = {
    id: null,
    name: '',
    base_url: '',
    auth_type: 'none',
    auth_config_token: '',
    auth_config_username: '',
    auth_config_password: '',
  }
}

function openNewSuiteDialog() {
  resetSuiteForm()
  isEditingSuite.value = false
  suiteDialogVisible.value = true
}

function openEditSuiteDialog(suite: ApiTestSuite) {
  suiteForm.value = {
    id: suite.id,
    name: suite.name,
    base_url: suite.base_url,
    auth_type: suite.auth_type || 'none',
    auth_config_token: (suite.auth_config as Record<string, string>)?.token || '',
    auth_config_username: (suite.auth_config as Record<string, string>)?.username || '',
    auth_config_password: (suite.auth_config as Record<string, string>)?.password || '',
  }
  isEditingSuite.value = true
  suiteDialogVisible.value = true
}

async function saveSuite() {
  const form = suiteForm.value
  if (!form.name.trim()) {
    ElMessage.warning('请填写套件名称')
    return
  }
  suiteDialogBusy.value = true
  try {
    let authConfig: Record<string, unknown> | null = null
    if (form.auth_type === 'bearer') {
      authConfig = { token: form.auth_config_token }
    } else if (form.auth_type === 'basic') {
      authConfig = { username: form.auth_config_username, password: form.auth_config_password }
    }

    const payload = {
      name: form.name.trim(),
      base_url: form.base_url.trim(),
      auth_type: form.auth_type === 'none' ? null : form.auth_type,
      auth_config: authConfig,
    }

    if (isEditingSuite.value && form.id) {
      await updateApiTestSuite(form.id, payload)
      ElMessage.success('套件已更新')
    } else {
      await createApiTestSuite(payload)
      ElMessage.success('套件已创建')
    }
    suiteDialogVisible.value = false
    await loadSuites()
    if (isEditingSuite.value && form.id) {
      await selectSuite(form.id)
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '保存套件失败')
  } finally {
    suiteDialogBusy.value = false
  }
}

async function removeSuite(suite: ApiTestSuite) {
  try {
    await ElMessageBox.confirm(`确认删除套件「${suite.name}」及其所有用例？`, '删除套件', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
    await deleteApiTestSuite(suite.id)
    if (selectedSuite.value?.id === suite.id) {
      selectedSuite.value = null
    }
    await loadSuites()
    ElMessage.success('套件已删除')
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error(error instanceof Error ? error.message : '删除失败')
    }
  }
}

function resetCaseForm() {
  caseForm.value = {
    id: null,
    name: '',
    method: 'GET',
    path: '',
    headers: [],
    params: [],
    bodyText: '',
    expected_status: 200,
    expected_body_contains: '',
    expected_schema: '',
    extract_vars: [],
    tags: '',
    priority: 'P1',
  }
}

function openNewCaseDialog() {
  resetCaseForm()
  isEditingCase.value = false
  caseDialogVisible.value = true
}

function openEditCaseDialog(caseItem: ApiTestCase) {
  caseForm.value = {
    id: caseItem.id,
    name: caseItem.name,
    method: caseItem.method,
    path: caseItem.path,
    headers: recordToKv(caseItem.headers),
    params: recordToKv(caseItem.params as Record<string, string>),
    bodyText: caseItem.body ? JSON.stringify(caseItem.body, null, 2) : '',
    expected_status: caseItem.expected_status,
    expected_body_contains: caseItem.expected_body_contains || '',
    expected_schema: caseItem.expected_schema ? JSON.stringify(caseItem.expected_schema, null, 2) : '',
    extract_vars: recordToKv(caseItem.extract_vars as Record<string, string>),
    tags: caseItem.tags || '',
    priority: caseItem.priority || 'P1',
  }
  isEditingCase.value = true
  caseDialogVisible.value = true
}

async function saveCase() {
  const form = caseForm.value
  if (!form.name.trim()) {
    ElMessage.warning('请填写用例名称')
    return
  }
  if (!selectedSuite.value) return

  caseDialogBusy.value = true
  try {
    let body: Record<string, unknown> | null = null
    if (form.bodyText.trim()) {
      try {
        body = JSON.parse(form.bodyText)
      } catch {
        ElMessage.warning('请求体 JSON 格式不正确')
        caseDialogBusy.value = false
        return
      }
    }

    let schema: Record<string, unknown> | null = null
    if (form.expected_schema.trim()) {
      try {
        schema = JSON.parse(form.expected_schema)
      } catch {
        ElMessage.warning('预期 Schema JSON 格式不正确')
        caseDialogBusy.value = false
        return
      }
    }

    const payload = {
      name: form.name.trim(),
      method: form.method,
      path: form.path.trim(),
      headers: kvToRecord(form.headers),
      params: kvToRecord(form.params),
      body,
      expected_status: form.expected_status,
      expected_body_contains: form.expected_body_contains.trim() || null,
      expected_schema: schema,
      extract_vars: kvToRecord(form.extract_vars) || null,
      tags: form.tags.trim() || null,
      priority: form.priority || null,
    }

    if (isEditingCase.value && form.id) {
      await updateApiTestCase(form.id, payload)
      ElMessage.success('用例已更新')
    } else {
      await createApiTestCase(selectedSuite.value.id, payload)
      ElMessage.success('用例已创建')
    }
    caseDialogVisible.value = false
    await selectSuite(selectedSuite.value.id)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '保存用例失败')
  } finally {
    caseDialogBusy.value = false
  }
}

async function removeCase(caseItem: ApiTestCase) {
  try {
    await ElMessageBox.confirm(`确认删除用例「${caseItem.name}」？`, '删除用例', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
    await deleteApiTestCase(caseItem.id)
    if (selectedSuite.value) {
      await selectSuite(selectedSuite.value.id)
    }
    ElMessage.success('用例已删除')
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error(error instanceof Error ? error.message : '删除失败')
    }
  }
}

async function runCase(caseItem: ApiTestCase) {
  runningCaseIds.value = new Set([...runningCaseIds.value, caseItem.id])
  try {
    const execution = await runApiTestCase(caseItem.id)
    currentExecution.value = execution
    resultDrawerVisible.value = true
    if (selectedSuite.value) {
      await selectSuite(selectedSuite.value.id)
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '执行用例失败')
  } finally {
    const next = new Set(runningCaseIds.value)
    next.delete(caseItem.id)
    runningCaseIds.value = next
  }
}

async function runSuite() {
  if (!selectedSuite.value) return
  runningSuiteId.value = selectedSuite.value.id
  try {
    const result: ApiTestSuiteRunResponse = await runApiTestSuite(selectedSuite.value.id)
    if (result.executions.length > 0) {
      currentExecution.value = result.executions[result.executions.length - 1]
      resultDrawerVisible.value = true
    }
    await selectSuite(selectedSuite.value.id)
    const passed = result.executions.filter(e => e.run_result === 'passed').length
    const failed = result.executions.filter(e => e.run_result === 'failed').length
    ElMessage.success(`套件执行完成：${passed} 通过，${failed} 失败`)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '执行套件失败')
  } finally {
    runningSuiteId.value = null
  }
}

async function loadSuites() {
  suitesLoading.value = true
  try {
    suites.value = await fetchApiTestSuites()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '加载套件列表失败')
  } finally {
    suitesLoading.value = false
  }
}

async function selectSuite(suiteId: number) {
  suiteDetailLoading.value = true
  try {
    selectedSuite.value = await fetchApiTestSuite(suiteId)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '加载套件详情失败')
  } finally {
    suiteDetailLoading.value = false
  }
}

function showExecutionDetail(execution: ApiTestExecution) {
  currentExecution.value = execution
  resultDrawerVisible.value = true
}

function formatJson(obj: unknown): string {
  if (!obj) return ''
  try {
    return JSON.stringify(obj, null, 2)
  } catch {
    return String(obj)
  }
}

function statusColor(status: number | null): string {
  if (!status) return ''
  if (status >= 200 && status < 300) return 'var(--el-color-success)'
  if (status >= 400 && status < 500) return 'var(--el-color-warning)'
  if (status >= 500) return 'var(--el-color-danger)'
  return 'var(--el-color-info)'
}

const suiteRunProgress = computed(() => {
  if (!selectedSuite.value || !runningSuiteId.value) return ''
  return `正在执行套件: ${selectedSuite.value.name}`
})

onMounted(() => {
  loadSuites()
})
</script>

<template>
  <div class="page-shell">
    <header class="topbar">
      <div class="topbar-left">
        <h1 class="page-title">接口自动化测试</h1>
        <span v-if="suiteRunProgress" class="run-progress">{{ suiteRunProgress }}</span>
      </div>
      <div class="topbar-actions">
        <el-button :icon="Refresh" size="small" @click="loadSuites">刷新</el-button>
      </div>
    </header>

    <div class="main-content">
      <div class="left-sidebar">
        <div class="sidebar-section">
          <div class="sidebar-header">
            <span>接口测试套件</span>
            <el-button :icon="Plus" size="small" text @click="openNewSuiteDialog" />
          </div>
          <div class="suite-list" v-loading="suitesLoading">
            <button
              v-for="suite in suites"
              :key="suite.id"
              class="suite-item"
              :class="{ active: selectedSuite?.id === suite.id }"
              type="button"
              @click="selectSuite(suite.id)"
            >
              <div class="suite-info">
                <span class="suite-name">{{ suite.name }}</span>
                <span class="suite-meta">{{ suite.base_url || '未设置 Base URL' }}</span>
              </div>
              <div class="suite-actions" @click.stop>
                <el-button :icon="Edit" size="small" text @click="openEditSuiteDialog(suite)" />
                <el-button :icon="Delete" size="small" text type="danger" @click="removeSuite(suite)" />
              </div>
            </button>
            <div v-if="suites.length === 0 && !suitesLoading" class="empty-sidebar">
              <span>暂无套件，点击 + 创建</span>
            </div>
          </div>
        </div>
      </div>

      <div class="right-content">
        <div v-if="!selectedSuite" class="empty-state">
          <h2>接口自动化测试</h2>
          <p>在左侧选择或新建一个接口测试套件，开始管理接口用例</p>
        </div>

        <div v-else class="suite-detail">
          <div class="detail-header">
            <div>
              <p class="eyebrow">接口测试套件</p>
              <h2>{{ selectedSuite.name }}</h2>
              <p class="suite-summary">
                Base URL: {{ selectedSuite.base_url || '-' }}
                <el-tag v-if="selectedSuite.auth_type && selectedSuite.auth_type !== 'none'" size="small" effect="light" style="margin-left: 8px">
                  认证: {{ selectedSuite.auth_type }}
                </el-tag>
                <span style="margin-left: 8px">{{ selectedSuite.cases?.length ?? 0 }} 条用例</span>
              </p>
            </div>
            <div class="detail-actions">
              <el-button :icon="Plus" size="small" @click="openNewCaseDialog">新增用例</el-button>
              <el-button
                :icon="VideoPlay"
                :loading="runningSuiteId === selectedSuite.id"
                :disabled="!selectedSuite.cases?.length"
                size="small"
                type="primary"
                @click="runSuite"
              >
                运行套件
              </el-button>
            </div>
          </div>

          <el-table
            v-loading="suiteDetailLoading"
            :data="selectedSuite.cases || []"
            class="case-table"
            stripe
            height="100%"
            row-key="id"
          >
            <el-table-column prop="sequence" label="序号" width="64" />
            <el-table-column prop="name" label="用例名称" min-width="160" show-overflow-tooltip />
            <el-table-column label="请求方法" width="100">
              <template #default="{ row }">
                <el-tag :type="methodType(row.method)" effect="dark" size="small" class="method-tag">
                  {{ row.method }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="path" label="路径" min-width="180" show-overflow-tooltip />
            <el-table-column label="预期状态码" width="100">
              <template #default="{ row }">
                <span class="mono">{{ row.expected_status }}</span>
              </template>
            </el-table-column>
            <el-table-column label="优先级" width="80">
              <template #default="{ row }">
                <el-tag
                  v-if="row.priority"
                  :type="row.priority === 'P0' ? 'danger' : row.priority === 'P1' ? 'warning' : 'info'"
                  effect="light"
                  size="small"
                >
                  {{ row.priority }}
                </el-tag>
                <span v-else>-</span>
              </template>
            </el-table-column>
            <el-table-column label="最新结果" width="90">
              <template #default="{ row }">
                <el-tag :type="resultType(row.latest_result)" effect="light" size="small">
                  {{ resultLabel(row.latest_result) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="latest_result_note" label="结果说明" min-width="140" show-overflow-tooltip />
            <el-table-column label="操作" width="200" fixed="right">
              <template #default="{ row }">
                <el-button
                  :icon="VideoPlay"
                  :loading="runningCaseIds.has(row.id)"
                  size="small"
                  type="primary"
                  text
                  @click="runCase(row)"
                >
                  运行
                </el-button>
                <el-button :icon="Edit" size="small" text @click="openEditCaseDialog(row)" />
                <el-button :icon="Delete" size="small" text type="danger" @click="removeCase(row)" />
              </template>
            </el-table-column>
          </el-table>
        </div>
      </div>
    </div>

    <!-- Suite Dialog -->
    <el-dialog
      v-model="suiteDialogVisible"
      :title="isEditingSuite ? '编辑套件' : '新建套件'"
      width="520px"
      destroy-on-close
    >
      <el-form label-position="top" class="dialog-form">
        <el-form-item label="套件名称" required>
          <el-input v-model="suiteForm.name" placeholder="例如：用户服务接口" />
        </el-form-item>
        <el-form-item label="Base URL">
          <el-input v-model="suiteForm.base_url" placeholder="例如：https://api.example.com" />
        </el-form-item>
        <el-form-item label="认证方式">
          <el-select v-model="suiteForm.auth_type">
            <el-option label="无认证" value="none" />
            <el-option label="Bearer Token" value="bearer" />
            <el-option label="Basic Auth" value="basic" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="suiteForm.auth_type === 'bearer'" label="Token">
          <el-input v-model="suiteForm.auth_config_token" placeholder="Bearer Token 值" />
        </el-form-item>
        <template v-if="suiteForm.auth_type === 'basic'">
          <el-form-item label="用户名">
            <el-input v-model="suiteForm.auth_config_username" placeholder="Basic Auth 用户名" />
          </el-form-item>
          <el-form-item label="密码">
            <el-input v-model="suiteForm.auth_config_password" type="password" show-password placeholder="Basic Auth 密码" />
          </el-form-item>
        </template>
      </el-form>
      <template #footer>
        <el-button @click="suiteDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="suiteDialogBusy" @click="saveSuite">保存</el-button>
      </template>
    </el-dialog>

    <!-- Case Dialog -->
    <el-dialog
      v-model="caseDialogVisible"
      :title="isEditingCase ? '编辑用例' : '新增用例'"
      width="680px"
      destroy-on-close
    >
      <el-form label-position="top" class="dialog-form">
        <div class="form-row">
          <el-form-item label="用例名称" required class="form-item-flex">
            <el-input v-model="caseForm.name" placeholder="例如：获取用户列表" />
          </el-form-item>
          <el-form-item label="优先级" style="width: 120px">
            <el-select v-model="caseForm.priority">
              <el-option label="P0" value="P0" />
              <el-option label="P1" value="P1" />
              <el-option label="P2" value="P2" />
              <el-option label="P3" value="P3" />
            </el-select>
          </el-form-item>
        </div>
        <div class="form-row">
          <el-form-item label="请求方法" style="width: 140px">
            <el-select v-model="caseForm.method">
              <el-option label="GET" value="GET" />
              <el-option label="POST" value="POST" />
              <el-option label="PUT" value="PUT" />
              <el-option label="DELETE" value="DELETE" />
              <el-option label="PATCH" value="PATCH" />
            </el-select>
          </el-form-item>
          <el-form-item label="路径" required class="form-item-flex">
            <el-input v-model="caseForm.path" placeholder="例如：/api/users" />
          </el-form-item>
        </div>

        <el-form-item label="请求头 (Headers)">
          <div class="kv-editor">
            <div v-for="(h, idx) in caseForm.headers" :key="idx" class="kv-row">
              <el-input v-model="h.key" placeholder="Key" size="small" />
              <el-input v-model="h.value" placeholder="Value" size="small" />
              <el-button :icon="Delete" size="small" text type="danger" @click="removeKvPair(caseForm.headers, idx)" />
            </div>
            <el-button :icon="Plus" size="small" @click="addKvPair(caseForm.headers)">添加</el-button>
          </div>
        </el-form-item>

        <el-form-item label="查询参数 (Params)">
          <div class="kv-editor">
            <div v-for="(p, idx) in caseForm.params" :key="idx" class="kv-row">
              <el-input v-model="p.key" placeholder="Key" size="small" />
              <el-input v-model="p.value" placeholder="Value" size="small" />
              <el-button :icon="Delete" size="small" text type="danger" @click="removeKvPair(caseForm.params, idx)" />
            </div>
            <el-button :icon="Plus" size="small" @click="addKvPair(caseForm.params)">添加</el-button>
          </div>
        </el-form-item>

        <el-form-item label="请求体 (Body JSON)">
          <el-input
            v-model="caseForm.bodyText"
            type="textarea"
            :rows="5"
            placeholder='{"key": "value"}'
          />
        </el-form-item>

        <div class="form-row">
          <el-form-item label="预期状态码" style="width: 140px">
            <el-input-number v-model="caseForm.expected_status" :min="100" :max="599" controls-position="right" />
          </el-form-item>
          <el-form-item label="预期响应包含" class="form-item-flex">
            <el-input v-model="caseForm.expected_body_contains" placeholder="响应体应包含的文本" />
          </el-form-item>
        </div>

        <el-form-item label="预期 Schema (JSON)">
          <el-input
            v-model="caseForm.expected_schema"
            type="textarea"
            :rows="4"
            placeholder='{"type": "object", "required": ["id"]}'
          />
        </el-form-item>

        <el-form-item label="提取变量 (Extract Vars)">
          <div class="kv-editor">
            <div v-for="(ev, idx) in caseForm.extract_vars" :key="idx" class="kv-row">
              <el-input v-model="ev.key" placeholder="变量名" size="small" />
              <el-input v-model="ev.value" placeholder="JSON Path" size="small" />
              <el-button :icon="Delete" size="small" text type="danger" @click="removeKvPair(caseForm.extract_vars, idx)" />
            </div>
            <el-button :icon="Plus" size="small" @click="addKvPair(caseForm.extract_vars)">添加</el-button>
          </div>
        </el-form-item>

        <el-form-item label="标签">
          <el-input v-model="caseForm.tags" placeholder="多个标签以逗号分隔" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="caseDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="caseDialogBusy" @click="saveCase">保存</el-button>
      </template>
    </el-dialog>

    <!-- Execution Result Drawer -->
    <el-drawer
      v-model="resultDrawerVisible"
      title="执行结果"
      size="520px"
      direction="rtl"
      destroy-on-close
    >
      <template v-if="currentExecution">
        <div class="exec-result-header">
          <el-tag :type="resultType(currentExecution.run_result)" effect="dark" size="large">
            {{ resultLabel(currentExecution.run_result) }}
          </el-tag>
          <span v-if="currentExecution.response_time_ms != null" class="exec-time">
            耗时 {{ currentExecution.response_time_ms }}ms
          </span>
        </div>

        <el-descriptions title="请求信息" :column="1" border class="exec-section">
          <el-descriptions-item label="方法 & URL">
            <el-tag :type="methodType(currentExecution.request_method)" effect="dark" size="small" class="method-tag">
              {{ currentExecution.request_method }}
            </el-tag>
            <span class="mono" style="margin-left: 8px">{{ currentExecution.request_url }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="请求头">
            <pre class="json-block">{{ formatJson(currentExecution.request_headers) }}</pre>
          </el-descriptions-item>
          <el-descriptions-item label="请求体">
            <pre class="json-block">{{ formatJson(currentExecution.request_body) }}</pre>
          </el-descriptions-item>
        </el-descriptions>

        <el-descriptions title="响应信息" :column="1" border class="exec-section">
          <el-descriptions-item label="状态码">
            <span class="status-code" :style="{ color: statusColor(currentExecution.response_status) }">
              {{ currentExecution.response_status ?? '-' }}
            </span>
          </el-descriptions-item>
          <el-descriptions-item v-if="currentExecution.response_time_ms != null" label="响应时间">
            {{ currentExecution.response_time_ms }}ms
          </el-descriptions-item>
          <el-descriptions-item label="响应头">
            <pre class="json-block">{{ formatJson(currentExecution.response_headers) }}</pre>
          </el-descriptions-item>
          <el-descriptions-item label="响应体">
            <pre class="json-block">{{ currentExecution.response_body_text || formatJson(currentExecution.response_body) }}</pre>
          </el-descriptions-item>
        </el-descriptions>

        <el-descriptions title="断言详情" :column="1" border class="exec-section">
          <template v-if="currentExecution.assertion_detail">
            <el-descriptions-item label="状态码检查">
              <el-tag :type="(currentExecution.assertion_detail as Record<string, unknown>).status_ok ? 'success' : 'danger'" effect="light" size="small">
                {{ (currentExecution.assertion_detail as Record<string, unknown>).status_ok ? '通过' : '未通过' }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="内容包含检查">
              <el-tag :type="(currentExecution.assertion_detail as Record<string, unknown>).body_contains_ok ? 'success' : 'danger'" effect="light" size="small">
                {{ (currentExecution.assertion_detail as Record<string, unknown>).body_contains_ok ? '通过' : '未通过' }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="Schema 检查">
              <el-tag :type="(currentExecution.assertion_detail as Record<string, unknown>).schema_ok ? 'success' : 'danger'" effect="light" size="small">
                {{ (currentExecution.assertion_detail as Record<string, unknown>).schema_ok ? '通过' : '未通过' }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item
              v-if="((currentExecution.assertion_detail as Record<string, unknown>).errors as unknown[])?.length"
              label="错误列表"
            >
              <ul class="error-list">
                <li v-for="(err, idx) in ((currentExecution.assertion_detail as Record<string, unknown>).errors as unknown[])" :key="idx">
                  {{ String(err) }}
                </li>
              </ul>
            </el-descriptions-item>
          </template>
          <el-descriptions-item v-else label="断言结果">
            <span>{{ currentExecution.result_note || '无断言详情' }}</span>
          </el-descriptions-item>
        </el-descriptions>
      </template>
    </el-drawer>
  </div>
</template>

<style scoped>
.page-shell {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
  background: var(--bg-primary);
}

.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  height: 48px;
  padding: 0 16px;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-nav);
  color: var(--text-primary);
  flex-shrink: 0;
}

.topbar-left {
  display: flex;
  align-items: center;
  gap: 16px;
  min-width: 0;
}

.page-title {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-inverse);
}

.run-progress {
  color: var(--el-color-primary);
  font-size: 12px;
}

.topbar-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.main-content {
  display: flex;
  flex: 1;
  min-width: 0;
  overflow: hidden;
}

.left-sidebar {
  display: flex;
  flex-direction: column;
  width: clamp(220px, 24vw, 280px);
  border-right: 1px solid var(--border-color);
  background: var(--bg-sidebar);
  color: var(--text-primary);
  flex-shrink: 0;
  overflow: hidden;
}

.sidebar-section {
  display: flex;
  flex-direction: column;
  flex: 1;
  overflow: hidden;
}

.sidebar-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 36px;
  padding: 0 12px;
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: var(--text-secondary);
  flex-shrink: 0;
}

.suite-list {
  flex: 1;
  overflow: auto;
  padding: 4px 0;
}

.suite-item {
  display: flex;
  align-items: center;
  gap: 4px;
  width: 100%;
  padding: 10px 12px;
  border: 0;
  background: transparent;
  color: var(--text-primary);
  cursor: pointer;
  text-align: left;
  transition: background 0.15s;
}

.suite-item:hover {
  background: var(--bg-tertiary);
}

.suite-item.active {
  background: var(--bg-tertiary);
  border-left: 3px solid var(--accent);
}

.suite-info {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
  gap: 2px;
}

.suite-name {
  font-size: 13px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.suite-meta {
  color: var(--text-muted);
  font-size: 11px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
}

.suite-actions {
  display: flex;
  gap: 0;
  opacity: 0;
  transition: opacity 0.15s;
}

.suite-item:hover .suite-actions {
  opacity: 1;
}

.empty-sidebar {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 32px 16px;
  color: var(--text-muted);
  font-size: 12px;
}

.right-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  background: var(--bg-primary);
  overflow: hidden;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 16px;
  height: 100%;
  color: var(--text-muted);
}

.empty-state h2 {
  margin: 0;
  font-size: 20px;
  font-weight: 500;
  color: var(--text-primary);
}

.empty-state p {
  margin: 0;
  font-size: 13px;
}

.suite-detail {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: 16px;
  gap: 12px;
  overflow: hidden;
}

.detail-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  flex-shrink: 0;
}

.detail-header h2 {
  margin: 2px 0 4px;
  color: var(--text-primary);
  font-size: 20px;
  font-weight: 600;
}

.eyebrow {
  margin: 0;
  color: var(--accent);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.3px;
  text-transform: uppercase;
}

.suite-summary {
  margin: 0;
  color: var(--text-secondary);
  font-size: 12px;
}

.detail-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
}

.case-table {
  flex: 1;
  min-height: 0;
}

.method-tag {
  min-width: 56px;
  text-align: center;
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 11px;
}

.mono {
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 12px;
}

.dialog-form {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.form-row {
  display: flex;
  gap: 12px;
}

.form-item-flex {
  flex: 1;
  min-width: 0;
}

.kv-editor {
  display: flex;
  flex-direction: column;
  gap: 6px;
  width: 100%;
}

.kv-row {
  display: flex;
  gap: 6px;
  align-items: center;
}

.kv-row .el-input {
  flex: 1;
  min-width: 0;
}

.exec-result-header {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 20px;
}

.exec-time {
  color: var(--text-secondary);
  font-size: 13px;
}

.exec-section {
  margin-bottom: 20px;
}

.json-block {
  max-height: 200px;
  margin: 0;
  padding: 8px;
  overflow: auto;
  background: var(--bg-tertiary);
  border-radius: 4px;
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
}

.status-code {
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 18px;
  font-weight: 700;
}

.error-list {
  margin: 0;
  padding-left: 16px;
  color: var(--el-color-danger);
  font-size: 12px;
  line-height: 1.6;
}

:deep(.el-descriptions__title) {
  font-size: 14px;
  font-weight: 600;
}

@media (max-width: 900px) {
  .main-content {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    grid-template-rows: auto minmax(0, 1fr);
  }
  .left-sidebar {
    width: auto;
    max-height: 220px;
    border-right: 0;
    border-bottom: 1px solid var(--border-color);
  }
}

@media (max-width: 720px) {
  .topbar {
    height: auto;
    min-height: 48px;
    flex-wrap: wrap;
    align-items: flex-start;
    padding: 8px 10px;
  }
  .detail-header {
    flex-direction: column;
    align-items: stretch;
  }
  .detail-actions {
    justify-content: flex-start;
  }
  .suite-detail {
    padding: 10px;
  }
  .form-row {
    flex-direction: column;
  }
}
</style>
