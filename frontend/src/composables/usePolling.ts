import { ref, onUnmounted } from 'vue'

export interface UsePollingOptions {
  interval?: number
  immediate?: boolean
  onError?: (error: Error) => void
}

export function usePolling(
  fn: () => Promise<void>,
  options: UsePollingOptions = {}
) {
  const { interval = 5000, immediate = false, onError } = options

  const isPolling = ref(false)
  const isRunning = ref(false)
  const error = ref<Error | null>(null)
  let timer: ReturnType<typeof globalThis.setInterval> | null = null

  async function execute() {
    // Prevent overlapping executions
    if (isRunning.value) return
    isRunning.value = true
    try {
      await fn()
      error.value = null
    } catch (e) {
      error.value = e instanceof Error ? e : new Error(String(e))
      onError?.(error.value)
    } finally {
      isRunning.value = false
    }
  }

  function start() {
    if (isPolling.value) return
    isPolling.value = true
    if (immediate) execute()
    timer = globalThis.setInterval(execute, interval)
  }

  function stop() {
    if (timer) {
      clearInterval(timer)
      timer = null
    }
    isPolling.value = false
  }

  function restart() {
    stop()
    start()
  }

  function updateInterval(newInterval: number) {
    if (isPolling.value && timer) {
      clearInterval(timer)
      timer = globalThis.setInterval(execute, newInterval)
    }
  }

  onUnmounted(() => {
    stop()
  })

  return {
    isPolling,
    isRunning,
    error,
    start,
    stop,
    restart,
    updateInterval,
    execute,
  }
}
