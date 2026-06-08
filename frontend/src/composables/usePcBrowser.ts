import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  openPCBrowser,
  closePCBrowser,
  fetchPCBrowserSnapshot,
  screenshotPCBrowser,
  clickPCBrowserElement,
  fillPCBrowserElement,
  pressPCBrowserKey,
  hoverPCBrowserElement,
  scrollPCBrowser,
  findAndClickPCBrowser,
  findAndFillPCBrowser,
  getPCBrowserUrl,
  getPCBrowserTitle,
  fetchPCBrowserLogs,
  getAssetUrl,
  type PCBrowserElement,
  type PCBrowserLogEntry,
} from '../api'

export function usePcBrowser(sessionName: string) {
  const url = ref('')
  const busy = ref(false)
  const connected = ref(false)
  const headedMode = ref(false)
  const browserUrl = ref('')
  const browserTitle = ref('')
  const latestScreenshot = ref('')
  const previewScreenshot = ref('')
  const elements = ref<PCBrowserElement[]>([])
  const logs = ref<PCBrowserLogEntry[]>([])

  // Recording state
  const pcRecordingEnabled = ref(false)
  const pcGeneratedCode = ref('')
  const pcSelectedElement = ref<PCBrowserElement | null>(null)
  const screenshotClickEnabled = ref(false)
  const autoRefreshActive = ref(false)
  const quickActionBusy = ref(false)

  // Agent auto-screenshot state
  let agentAutoScreenshotTimer: number | null = null
  const agentAutoScreenshotActive = ref(false)

  let autoRefreshTimer: number | null = null

  async function connectBrowser(headed = false) {
    if (connected.value) return
    busy.value = true
    try {
      const targetUrl = url.value || 'https://www.baidu.com'
      await openPCBrowser(targetUrl, { session: sessionName, headed })
      connected.value = true
      headedMode.value = headed
      await refreshSnapshot()
      browserUrl.value = await getPCBrowserUrl(sessionName)
      browserTitle.value = await getPCBrowserTitle(sessionName)
    } catch (error) {
      ElMessage.error(error instanceof Error ? error.message : '连接浏览器失败')
    } finally {
      busy.value = false
    }
  }

  async function disconnectBrowser() {
    if (!connected.value) return
    busy.value = true
    try {
      stopAutoRefresh()
      stopAgentAutoScreenshot()
      await closePCBrowser(sessionName)
      connected.value = false
      headedMode.value = false
      browserUrl.value = ''
      browserTitle.value = ''
      url.value = ''
      latestScreenshot.value = ''
      previewScreenshot.value = ''
      elements.value = []
      logs.value = []
    } catch (error) {
      ElMessage.error(error instanceof Error ? error.message : '断开浏览器失败')
    } finally {
      busy.value = false
    }
  }

  async function refreshSnapshot() {
    if (!connected.value) return
    try {
      elements.value = await fetchPCBrowserSnapshot(sessionName, true)
      browserUrl.value = await getPCBrowserUrl(sessionName)
      browserTitle.value = await getPCBrowserTitle(sessionName)
    } catch {
      // ignore
    }
  }

  async function refreshLogs() {
    if (!connected.value) return
    try {
      logs.value = await fetchPCBrowserLogs(sessionName)
    } catch {
      // ignore
    }
  }

  async function captureStepScreenshot() {
    if (!connected.value) return
    quickActionBusy.value = true
    try {
      const result = await screenshotPCBrowser(sessionName)
      if (result.url) {
        latestScreenshot.value = getAssetUrl(result.url)
      } else if (result.path) {
        latestScreenshot.value = result.path
      }
    } catch (error) {
      ElMessage.error(error instanceof Error ? error.message : '截图失败')
    } finally {
      quickActionBusy.value = false
    }
  }

  function handleScreenshotClick(_event: { x: number; y: number }) {
    // PC browser screenshot click - no-op or future feature
  }

  function togglePcRecording() {
    pcRecordingEnabled.value = !pcRecordingEnabled.value
    if (!pcRecordingEnabled.value) {
      pcGeneratedCode.value = ''
    }
  }

  function clickSelectedElement() {
    if (!pcSelectedElement.value) return
    void clickElement(pcSelectedElement.value.ref)
  }

  async function clickElement(elementRef: string) {
    if (!connected.value) return
    try {
      await clickPCBrowserElement(sessionName, elementRef)
      await refreshSnapshot()
    } catch (error) {
      ElMessage.error(error instanceof Error ? error.message : '点击元素失败')
    }
  }

  async function fillElement(elementRef: string, text: string) {
    if (!connected.value) return
    try {
      await fillPCBrowserElement(sessionName, elementRef, text)
      await refreshSnapshot()
    } catch (error) {
      ElMessage.error(error instanceof Error ? error.message : '填充元素失败')
    }
  }

  async function hoverElement(elementRef: string) {
    if (!connected.value) return
    try {
      await hoverPCBrowserElement(sessionName, elementRef)
      await refreshSnapshot()
    } catch (error) {
      ElMessage.error(error instanceof Error ? error.message : '悬停失败')
    }
  }

  async function findAndClick(text: string) {
    if (!connected.value) return
    quickActionBusy.value = true
    try {
      await findAndClickPCBrowser(sessionName, text)
      await refreshSnapshot()
    } catch (error) {
      ElMessage.error(error instanceof Error ? error.message : '查找点击失败')
    } finally {
      quickActionBusy.value = false
    }
  }

  async function findAndFill(label: string, text: string) {
    if (!connected.value) return
    quickActionBusy.value = true
    try {
      await findAndFillPCBrowser(sessionName, label, text)
      await refreshSnapshot()
    } catch (error) {
      ElMessage.error(error instanceof Error ? error.message : '查找填充失败')
    } finally {
      quickActionBusy.value = false
    }
  }

  async function pressKey(key: string) {
    if (!connected.value) return
    try {
      await pressPCBrowserKey(sessionName, key)
      await refreshSnapshot()
    } catch (error) {
      ElMessage.error(error instanceof Error ? error.message : '按键失败')
    }
  }

  async function scrollPage(direction: string, amount: number) {
    if (!connected.value) return
    try {
      await scrollPCBrowser(sessionName, direction, amount)
      await refreshSnapshot()
    } catch (error) {
      ElMessage.error(error instanceof Error ? error.message : '滚动失败')
    }
  }

  function toggleAutoRefresh() {
    autoRefreshActive.value = !autoRefreshActive.value
    if (autoRefreshActive.value) {
      startAutoRefresh()
    } else {
      stopAutoRefresh()
    }
  }

  function startAutoRefresh() {
    stopAutoRefresh()
    autoRefreshTimer = window.setInterval(() => {
      void refreshSnapshot()
    }, 2000)
    autoRefreshActive.value = true
  }

  function stopAutoRefresh() {
    if (autoRefreshTimer) {
      clearInterval(autoRefreshTimer)
      autoRefreshTimer = null
    }
    autoRefreshActive.value = false
  }

  function startAgentAutoScreenshot(intervalMs = 2500) {
    stopAgentAutoScreenshot()
    agentAutoScreenshotActive.value = true
    agentAutoScreenshotTimer = window.setInterval(async () => {
      if (!connected.value) return
      try {
        const result = await screenshotPCBrowser(sessionName)
        if (result.url) {
          latestScreenshot.value = getAssetUrl(result.url)
        } else if (result.path) {
          latestScreenshot.value = result.path
        }
      } catch {
        // ignore - agent might be between steps
      }
    }, intervalMs)
  }

  function stopAgentAutoScreenshot() {
    if (agentAutoScreenshotTimer) {
      clearInterval(agentAutoScreenshotTimer)
      agentAutoScreenshotTimer = null
    }
    agentAutoScreenshotActive.value = false
  }

  function resolveAssetUrl(path: string): string {
    return getAssetUrl(path)
  }

  return {
    url,
    busy,
    connected,
    headedMode,
    browserUrl,
    browserTitle,
    latestScreenshot,
    previewScreenshot,
    elements,
    logs,
    pcRecordingEnabled,
    pcGeneratedCode,
    pcSelectedElement,
    screenshotClickEnabled,
    autoRefreshActive,
    quickActionBusy,
    agentAutoScreenshotActive,
    connectBrowser,
    disconnectBrowser,
    refreshSnapshot,
    refreshLogs,
    captureStepScreenshot,
    handleScreenshotClick,
    togglePcRecording,
    clickSelectedElement,
    clickElement,
    fillElement,
    hoverElement,
    findAndClick,
    findAndFill,
    pressKey,
    scrollPage,
    toggleAutoRefresh,
    startAutoRefresh,
    stopAutoRefresh,
    startAgentAutoScreenshot,
    stopAgentAutoScreenshot,
    resolveAssetUrl,
  }
}