import { ref, onUnmounted } from 'vue'
import { getScriptOutputWebSocketUrl } from '../api'

export interface TerminalLine {
  id: number
  type: 'stdout' | 'stderr' | 'system' | 'exit'
  text: string
  timestamp: number
}

export function useScriptTerminal() {
  const lines = ref<TerminalLine[]>([])
  const isConnected = ref(false)
  const isRunning = ref(false)
  const lastReturnCode = ref<number | null>(null)
  const durationMs = ref<number | null>(null)

  let ws: WebSocket | null = null
  let lineId = 0

  function connect(runId: string) {
    disconnect()

    const url = getScriptOutputWebSocketUrl(runId)
    ws = new WebSocket(url)

    ws.onopen = () => {
      isConnected.value = true
      isRunning.value = true
      addLine('system', `Connected to run ${runId}`)
    }

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data)
        handleMessage(msg)
      } catch {
        addLine('stderr', event.data)
      }
    }

    ws.onclose = () => {
      isConnected.value = false
      isRunning.value = false
    }

    ws.onerror = () => {
      addLine('stderr', 'WebSocket connection error')
      isConnected.value = false
      isRunning.value = false
    }
  }

  function handleMessage(msg: { type: string; data?: string; returncode?: number; duration_ms?: number; message?: string }) {
    switch (msg.type) {
      case 'stdout':
        if (msg.data) addLine('stdout', msg.data)
        break
      case 'stderr':
        if (msg.data) addLine('stderr', msg.data)
        break
      case 'exit':
        isRunning.value = false
        lastReturnCode.value = msg.returncode ?? 0
        durationMs.value = msg.duration_ms ?? 0
        addLine('exit', `Process exited with code ${msg.returncode} (${msg.duration_ms}ms)`)
        break
      case 'error':
        addLine('stderr', `Error: ${msg.message}`)
        isRunning.value = false
        break
    }
  }

  function addLine(type: TerminalLine['type'], text: string) {
    lineId++
    lines.value.push({
      id: lineId,
      type,
      text: text.replace(/\n$/, ''),
      timestamp: Date.now(),
    })
  }

  function disconnect() {
    if (ws) {
      ws.close()
      ws = null
    }
    isConnected.value = false
  }

  function clear() {
    lines.value = []
    lineId = 0
    lastReturnCode.value = null
    durationMs.value = null
  }

  onUnmounted(() => {
    disconnect()
  })

  return {
    lines,
    isConnected,
    isRunning,
    lastReturnCode,
    durationMs,
    connect,
    disconnect,
    clear,
    addLine,
  }
}