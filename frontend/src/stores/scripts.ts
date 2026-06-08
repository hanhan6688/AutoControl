import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import {
  fetchScripts,
  fetchScriptTree,
  fetchScript,
  createScript as apiCreateScript,
  createFolder as apiCreateFolder,
  saveScript as apiSaveScript,
  deleteScript as apiDeleteScript,
  deleteFolder as apiDeleteFolder,
  runScript as apiRunScript,
  runScriptStream as apiRunScriptStream,
  fetchPythonEnvs,
  cancelScriptRun,
  type ScriptFile,
  type ScriptRunResult,
  type FileTreeItem,
  type PythonEnvsResponse,
} from '../api'

export const useScriptStore = defineStore('scripts', () => {
  const scripts = ref<ScriptFile[]>([])
  const scriptTree = ref<FileTreeItem[]>([])
  const activeScript = ref<ScriptFile | null>(null)
  const scriptContent = ref('')
  const originalContent = ref('')
  const loading = ref(false)
  const saving = ref(false)
  const running = ref(false)
  const runResult = ref<ScriptRunResult | null>(null)
  const pythonEnvs = ref<PythonEnvsResponse | null>(null)
  const selectedPythonPath = ref<string>('')
  const activeRunId = ref<string | null>(null)
  const error = ref<string | null>(null)

  const isDirty = computed(() => scriptContent.value !== originalContent.value)

  async function loadScripts() {
    loading.value = true
    error.value = null
    try {
      scripts.value = await fetchScripts()
    } catch (e) {
      error.value = e instanceof Error ? e.message : '获取脚本列表失败'
    } finally {
      loading.value = false
    }
  }

  async function loadScriptTree() {
    loading.value = true
    error.value = null
    try {
      scriptTree.value = await fetchScriptTree()
    } catch (e) {
      error.value = e instanceof Error ? e.message : '获取脚本树失败'
    } finally {
      loading.value = false
    }
  }

  async function openScript(script: ScriptFile) {
    loading.value = true
    error.value = null
    try {
      const result = await fetchScript(script.path)
      activeScript.value = script
      scriptContent.value = result.content
      originalContent.value = result.content
    } catch (e) {
      error.value = e instanceof Error ? e.message : '加载脚本失败'
    } finally {
      loading.value = false
    }
  }

  async function createScript(name: string, content = '', platform?: string | null) {
    saving.value = true
    error.value = null
    try {
      const script = await apiCreateScript(name, content, platform)
      scripts.value.push(script)
      await loadScriptTree()
      return script
    } catch (e) {
      error.value = e instanceof Error ? e.message : '创建脚本失败'
      return null
    } finally {
      saving.value = false
    }
  }

  async function createNewFolder(path: string) {
    saving.value = true
    error.value = null
    try {
      await apiCreateFolder(path)
      await loadScriptTree()
      return true
    } catch (e) {
      error.value = e instanceof Error ? e.message : '创建文件夹失败'
      return false
    } finally {
      saving.value = false
    }
  }

  async function saveActiveScript() {
    if (!activeScript.value) return false
    saving.value = true
    error.value = null
    try {
      await apiSaveScript(activeScript.value.path, scriptContent.value)
      originalContent.value = scriptContent.value
      return true
    } catch (e) {
      error.value = e instanceof Error ? e.message : '保存脚本失败'
      return false
    } finally {
      saving.value = false
    }
  }

  async function deleteScript(path: string) {
    saving.value = true
    error.value = null
    try {
      await apiDeleteScript(path)
      scripts.value = scripts.value.filter(s => s.path !== path)
      if (activeScript.value?.path === path) {
        activeScript.value = null
        scriptContent.value = ''
        originalContent.value = ''
      }
      await loadScriptTree()
      return true
    } catch (e) {
      error.value = e instanceof Error ? e.message : '删除脚本失败'
      return false
    } finally {
      saving.value = false
    }
  }

  async function deleteFolderByPath(path: string) {
    saving.value = true
    error.value = null
    try {
      await apiDeleteFolder(path)
      await loadScriptTree()
      return true
    } catch (e) {
      error.value = e instanceof Error ? e.message : '删除文件夹失败'
      return false
    } finally {
      saving.value = false
    }
  }

  async function runActiveScript(
    deviceUdid: string,
    options: { platform?: string; wdaUrl?: string | null } = {},
  ) {
    if (!activeScript.value) return null
    running.value = true
    error.value = null
    try {
      const result = await apiRunScript(activeScript.value.path, deviceUdid, options)
      runResult.value = result
      return result
    } catch (e) {
      error.value = e instanceof Error ? e.message : '运行脚本失败'
      return null
    } finally {
      running.value = false
    }
  }

  async function loadPythonEnvs() {
    try {
      pythonEnvs.value = await fetchPythonEnvs()
      if (!selectedPythonPath.value && pythonEnvs.value) {
        selectedPythonPath.value = pythonEnvs.value.current
      }
    } catch (e) {
      console.error('Failed to load Python envs:', e)
    }
  }

  function selectPythonPath(path: string) {
    selectedPythonPath.value = path
  }

  async function runActiveScriptStream(
    deviceUdid: string,
    options: { platform?: string; wdaUrl?: string | null } = {},
  ) {
    if (!activeScript.value) return null
    running.value = true
    error.value = null
    try {
      const result = await apiRunScriptStream(activeScript.value.path, deviceUdid, {
        ...options,
        pythonEnv: selectedPythonPath.value || undefined,
      })
      activeRunId.value = result.run_id
      return result
    } catch (e) {
      error.value = e instanceof Error ? e.message : '运行脚本失败'
      return null
    } finally {
      running.value = false
    }
  }

  async function cancelActiveRun() {
    if (!activeRunId.value) return
    try {
      await cancelScriptRun(activeRunId.value)
      activeRunId.value = null
    } catch (e) {
      console.error('Failed to cancel run:', e)
    }
  }

  function closeScript() {
    activeScript.value = null
    scriptContent.value = ''
    originalContent.value = ''
    runResult.value = null
  }

  return {
    scripts,
    scriptTree,
    activeScript,
    scriptContent,
    loading,
    saving,
    running,
    runResult,
    error,
    isDirty,
    pythonEnvs,
    selectedPythonPath,
    activeRunId,
    loadScripts,
    loadScriptTree,
    openScript,
    createScript,
    createNewFolder,
    saveActiveScript,
    deleteScript,
    deleteFolderByPath,
    runActiveScript,
    loadPythonEnvs,
    selectPythonPath,
    runActiveScriptStream,
    cancelActiveRun,
    closeScript,
  }
})
