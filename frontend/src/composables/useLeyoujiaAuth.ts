import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  fetchLeyoujiaAuthStatus,
  openLeyoujiaLogin,
  saveLeyoujiaAuthState,
  loadLeyoujiaAuthState,
  type LeyoujiaAuthStatus,
  type PCBrowserSessionResponse,
} from '../api'

export interface UseLeyoujiaAuthOptions {
  onBrowserConnected: (session: PCBrowserSessionResponse) => void
  startAutoRefresh: () => void
  stopAutoRefresh: () => void
}

export function useLeyoujiaAuth(sessionName: string, options: UseLeyoujiaAuthOptions) {
  const leyoujiaAuthEnv = ref<'test' | 'prod'>('test')
  const leyoujiaAuthBusy = ref(false)
  const loginPollingActive = ref(false)
  const currentLeyoujiaAuthStatus = ref<LeyoujiaAuthStatus | null>(null)
  const leyoujiaAuthSaved = ref(false)

  const leyoujiaAuthStatusText = computed(() => {
    const status = currentLeyoujiaAuthStatus.value
    if (!status) return '未检测'
    if (status.state_exists) return '已登录'
    return '未登录'
  })

  const leyoujiaLoginButtonText = computed(() => {
    if (leyoujiaAuthBusy.value) return '处理中...'
    const status = currentLeyoujiaAuthStatus.value
    if (status?.state_exists) return '重新登录'
    return '打开登录页'
  })

  let loginPollTimer: number | null = null

  async function loadLeyoujiaStatus(env: 'test' | 'prod') {
    try {
      const status = await fetchLeyoujiaAuthStatus(env)
      if (env === leyoujiaAuthEnv.value) {
        currentLeyoujiaAuthStatus.value = status
      }
      return status
    } catch {
      return null
    }
  }

  async function openLeyoujiaLoginPage() {
    leyoujiaAuthBusy.value = true
    try {
      const session = await openLeyoujiaLogin(sessionName, leyoujiaAuthEnv.value)
      options.onBrowserConnected(session)
      ElMessage.info('已打开登录页面，请在浏览器中完成登录')
      startLoginPolling()
    } catch (error) {
      ElMessage.error(error instanceof Error ? error.message : '打开登录页失败')
    } finally {
      leyoujiaAuthBusy.value = false
    }
  }

  function startLoginPolling() {
    stopLoginPolling()
    loginPollingActive.value = true
    let pollCount = 0
    loginPollTimer = window.setInterval(async () => {
      pollCount++
      const status = await loadLeyoujiaStatus(leyoujiaAuthEnv.value)
      if (status?.state_exists) {
        stopLoginPolling()
        leyoujiaAuthSaved.value = true
        ElMessage.success('检测到登录成功')
        options.startAutoRefresh()
      }
      if (pollCount >= 120) {
        stopLoginPolling()
        ElMessage.warning('登录检测超时，请手动保存登录状态')
      }
    }, 3000)
  }

  function stopLoginPolling() {
    if (loginPollTimer) {
      clearInterval(loginPollTimer)
      loginPollTimer = null
    }
    loginPollingActive.value = false
  }

  async function saveLeyoujiaLoginState() {
    leyoujiaAuthBusy.value = true
    try {
      const result = await saveLeyoujiaAuthState(sessionName, leyoujiaAuthEnv.value)
      leyoujiaAuthSaved.value = true
      ElMessage.success(result.status || '登录状态已保存')
      await loadLeyoujiaStatus(leyoujiaAuthEnv.value)
    } catch (error) {
      ElMessage.error(error instanceof Error ? error.message : '保存登录状态失败')
    } finally {
      leyoujiaAuthBusy.value = false
    }
  }

  async function loadLeyoujiaLoginState() {
    leyoujiaAuthBusy.value = true
    try {
      const result = await loadLeyoujiaAuthState(sessionName, leyoujiaAuthEnv.value)
      leyoujiaAuthSaved.value = Boolean(result.state_exists)
      ElMessage.success(result.status || '登录状态已加载')
      await loadLeyoujiaStatus(leyoujiaAuthEnv.value)
      if (result.state_exists) {
        options.startAutoRefresh()
      }
    } catch (error) {
      ElMessage.error(error instanceof Error ? error.message : '加载登录状态失败')
    } finally {
      leyoujiaAuthBusy.value = false
    }
  }

  return {
    leyoujiaAuthEnv,
    leyoujiaAuthBusy,
    loginPollingActive,
    currentLeyoujiaAuthStatus,
    leyoujiaAuthSaved,
    leyoujiaAuthStatusText,
    leyoujiaLoginButtonText,
    loadLeyoujiaStatus,
    openLeyoujiaLoginPage,
    saveLeyoujiaLoginState,
    loadLeyoujiaLoginState,
  }
}
