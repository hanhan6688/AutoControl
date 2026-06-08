import { ref, shallowRef, onUnmounted } from 'vue'

/** Return type of useScreenStream(), used for inject/provide typing */
export type ScreenStreamHandle = ReturnType<typeof useScreenStream>
import {
  getDeviceScreenWebSocketUrl,
  getDeviceScreenSize,
  tapDevicePoint,
  pressDeviceKey,
  swipeDevice,
  inputDeviceText,
  touchDown,
  touchMove,
  touchUp,
  apiBaseUrl,
} from '../api'
import { createH264Decoder } from '../h264Decoder'
import type { H264DecoderLike, DecoderMode } from '../h264Decoder'
import { io, Socket } from 'socket.io-client'

const electronAPI = typeof window !== 'undefined' ? (window as any).electronAPI : undefined
const isElectron = Boolean(electronAPI?.isElectron)

/** Quick check: does the ArrayBuffer start with H.264 NAL unit start code? */
function looksLikeH264(data: ArrayBuffer): boolean {
  if (data.byteLength < 4) return false
  const bytes = new Uint8Array(data)
  // 4-byte start code: 00 00 00 01
  if (bytes[0] === 0 && bytes[1] === 0 && bytes[2] === 0 && bytes[3] === 1) return true
  // 3-byte start code: 00 00 01
  if (bytes[0] === 0 && bytes[1] === 0 && bytes[2] === 1) return true
  return false
}

const DEFAULT_STREAM_MAX_FPS = 30
const DEFAULT_STREAM_MAX_SIZE = 720

export interface ScreenStreamOptions {
  platform?: string
  provider?: string
  maxFps?: number
  maxSize?: number
  wdaUrl?: string
  useExternalScrcpyWindow?: boolean
  useNativeScrcpySurface?: boolean
  /** Route control through HTTP APIs instead of the live screen socket. */
  preferApiTouchControl?: boolean
  /** Prefer SocketIO transport over raw WebSocket for screen + control. */
  useSocketio?: boolean
  /** Disable real-time touch control (read-only screen). Saves a socket + thread. */
  control?: boolean
}

export interface ScreenStreamState {
  udid: string
  isConnected: boolean
  isLoading: boolean
  error: string
  notice: string
  frameCount: number
  fps: number
  provider: string
  mimeType: string
  width: number
  height: number
  decoderMode: DecoderMode
  mode: 'websocket' | 'scrcpy-window' | 'scrcpy-native' | 'socketio'
  controlConnected: boolean
  controlMode: 'live' | 'fallback' | 'none'
}

export function useScreenStream() {
  const ws = ref<WebSocket | null>(null)
  const sioSocket = shallowRef<Socket | null>(null)
  const decoder = shallowRef<H264DecoderLike | null>(null)
  const decoderMode = ref<DecoderMode>('webcodecs')
  const canvas = ref<HTMLCanvasElement | null>(null)
  const nativeHost = ref<HTMLElement | null>(null)
  const videoEl = ref<HTMLVideoElement | null>(null)
  const yumeHost = ref<HTMLElement | null>(null)

  const state = ref<ScreenStreamState>({
    udid: '',
    isConnected: false,
    isLoading: false,
    error: '',
    notice: '',
    frameCount: 0,
    fps: 0,
    provider: '',
    mimeType: '',
    width: 0,
    height: 0,
    decoderMode: 'webcodecs',
    mode: 'websocket',
    controlConnected: false,
    controlMode: 'none',
  })

  let heartbeatTimer: number | null = null
  let reconnectTimer: number | null = null
  let reconnectAttempts = 0
  const maxReconnectAttempts = 3
  let currentOptions: ScreenStreamOptions = {}
  let fpsCounter = 0
  let fpsLastTime = 0
  let fpsTimer: number | null = null
  let nativeResizeTimer: number | null = null
  let lastNativeRectKey = ''
  let apiTouchChain: Promise<void> = Promise.resolve()
  let apiMoveRunning = false
  let latestApiMove: { x: number; y: number } | null = null
  let latestWsMove: { x: number; y: number } | null = null
  let wsMoveFrame: number | null = null
  let needsH264StreamRestartOnCanvasAttach = false

  function connect(udid: string, options: ScreenStreamOptions = {}) {
    const requestedControl = options.control ?? true
    if (state.value.isConnected && currentOptions.control !== requestedControl) {
      disconnect()
    }
    disconnect()
    currentOptions = {
      ...options,
      maxFps: options.maxFps ?? DEFAULT_STREAM_MAX_FPS,
      maxSize: options.maxSize ?? DEFAULT_STREAM_MAX_SIZE,
    }

    state.value.isLoading = true
    state.value.error = ''
    state.value.notice = ''
    state.value.udid = udid
    state.value.frameCount = 0
    state.value.fps = 0
    state.value.provider = ''
    state.value.mimeType = ''
    state.value.width = 0
    state.value.height = 0
    state.value.mode = resolveStreamMode(options)
    state.value.controlConnected = false
    state.value.controlMode = 'none'
    fpsCounter = 0
    fpsLastTime = performance.now()
    startFpsTimer()

    if (state.value.mode === 'scrcpy-window') {
      connectScrcpyWindow(udid)
      return
    }
    if (state.value.mode === 'scrcpy-native') {
      connectScrcpyNative(udid)
      return
    }
    if (state.value.mode === 'socketio') {
      connectSocketio(udid, options)
      return
    }

    connectWebSocket(udid, options)
  }

  function resolveStreamMode(options: ScreenStreamOptions): ScreenStreamState['mode'] {
    if (options.useSocketio) return 'socketio'
    if (!isElectron) return 'websocket'
    if (options.useExternalScrcpyWindow) return 'scrcpy-window'
    if (options.useNativeScrcpySurface === true) return 'scrcpy-native'
    return 'websocket'
  }

  // ---- Electron scrcpy window mode ----

  function connectScrcpyWindow(udid: string) {
    if (!electronAPI?.scrcpyStart) {
      state.value.error = 'Electron scrcpy API 不可用'
      state.value.isLoading = false
      return
    }

    electronAPI.scrcpyStart(udid, {
      maxSize: currentOptions.maxSize ?? 1280,
      maxFps: currentOptions.maxFps ?? 30,
    }).then((result: any) => {
      if (result?.running) {
        state.value.isConnected = true
        state.value.isLoading = false
        state.value.provider = 'scrcpy-window'
        state.value.notice = 'scrcpy 独立窗口已启动，操控按钮在本面板'
      } else if (result?.error) {
        state.value.error = result.error
        state.value.isLoading = false
      }
    }).catch((err: any) => {
      state.value.error = err?.message || '启动 scrcpy 失败'
      state.value.isLoading = false
    })

    if (electronAPI?.onScrcpyExited) {
      electronAPI.onScrcpyExited(() => {
        state.value.isConnected = false
        state.value.notice = 'scrcpy 窗口已关闭'
      })
    }
  }

  function disconnectScrcpyWindow() {
    if (electronAPI?.scrcpyStop) {
      electronAPI.scrcpyStop()
    }
    if (electronAPI?.removeScrcpyExitedListener) {
      electronAPI.removeScrcpyExitedListener()
    }
  }

  // ---- Electron native embedded scrcpy surface ----

  async function connectScrcpyNative(udid: string) {
    if (!electronAPI?.scrcpyNativeStart) {
      state.value.error = 'Electron 原生投屏 API 不可用'
      state.value.isLoading = false
      return
    }

    try {
      const host = await waitForNativeHost()
      if (!host) {
        state.value.error = '原生投屏容器未就绪'
        state.value.isLoading = false
        return
      }
      const result = await electronAPI.scrcpyNativeStart(udid, {
        maxSize: currentOptions.maxSize ?? 1280,
        maxFps: currentOptions.maxFps ?? 60,
        rect: nativeHostRect(host),
      })
      if (result?.running) {
        await refreshNativeDeviceSize(udid)
        state.value.isConnected = true
        state.value.isLoading = false
        state.value.provider = 'scrcpy-native'
        state.value.mimeType = 'native/scrcpy'
        state.value.notice = ''
        state.value.controlConnected = true
        state.value.controlMode = 'live'
        startNativeResizeSync()
      } else {
        state.value.error = result?.error || '启动原生投屏失败'
        state.value.isLoading = false
      }
    } catch (err: any) {
      state.value.error = err?.message || '启动原生投屏失败'
      state.value.isLoading = false
    }

    if (electronAPI?.onScrcpyNativeExited) {
      electronAPI.onScrcpyNativeExited(() => {
        state.value.isConnected = false
        state.value.notice = '原生投屏已关闭'
        stopNativeResizeSync()
      })
    }
  }

  function disconnectScrcpyNative() {
    stopNativeResizeSync()
    if (electronAPI?.scrcpyNativeStop) {
      electronAPI.scrcpyNativeStop()
    }
    if (electronAPI?.removeScrcpyNativeExitedListener) {
      electronAPI.removeScrcpyNativeExitedListener()
    }
  }

  // ---- SocketIO mode (unified screen + control) ----

  function connectSocketio(udid: string, options: ScreenStreamOptions) {
    const baseUrl = apiBaseUrl.replace(/^http/, 'ws')
    const socket = io(baseUrl, {
      path: '/ws/socket.io',
      transports: ['websocket'],
      reconnection: true,
      reconnectionAttempts: 3,
      reconnectionDelay: 2000,
    })
    sioSocket.value = socket

    socket.on('connect', () => {
      socket.emit('start', {
        udid,
        platform: options.platform ?? 'android',
        provider: currentOptions.provider ?? 'auto',
        max_fps: currentOptions.maxFps ?? 20,
        max_size: currentOptions.maxSize ?? 720,
        control: options.control ?? true,
        wda_url: options.wdaUrl,
      })
    })

    socket.on('connected', () => {
      state.value.isConnected = true
      state.value.isLoading = false
      state.value.controlConnected = true
      state.value.controlMode = 'live'
      reconnectAttempts = 0
    })

    socket.on('provider', (msg: any) => {
      state.value.provider = msg.provider ?? ''
      state.value.mimeType = msg.mime_type ?? ''
      if (msg.provider === 'scrcpy-h264' && !decoder.value) {
        initH264Decoder()
      }
    })

    socket.on('device_info', (msg: any) => {
      state.value.width = msg.screen_width ?? 0
      state.value.height = msg.screen_height ?? 0
    })

    socket.on('control_mode', (msg: any) => {
      const mode = msg.mode ?? 'adb_fallback'
      state.value.controlMode = mode === 'scrcpy' || mode === 'wda' ? 'live' : 'fallback'
      state.value.controlConnected = true
    })

    socket.on('frame', (data: ArrayBuffer) => {
      state.value.frameCount++
      fpsCounter++
      state.value.isConnected = true
      state.value.isLoading = false

      const isH264 = (
        state.value.provider === 'scrcpy-h264' ||
        state.value.mimeType === 'video/h264' ||
        looksLikeH264(data)
      )
      if (isH264) {
        if (!decoder.value) initH264Decoder()
        decoder.value?.feed(data)
        return
      }
      if (state.value.mimeType && state.value.mimeType.startsWith('image/')) {
        drawImageFrame(data)
      }
    })

    socket.on('error', (msg: any) => {
      state.value.error = msg.message || '投屏异常'
    })

    socket.on('disconnect', () => {
      state.value.isConnected = false
      state.value.controlConnected = false
      state.value.controlMode = 'none'
    })
  }

  function disconnectSocketio() {
    if (sioSocket.value) {
      sioSocket.value.disconnect()
      sioSocket.value = null
    }
  }

  async function refreshNativeDeviceSize(udid: string) {
    try {
      if (electronAPI?.getDeviceScreenSize) {
        const electronSize = await electronAPI.getDeviceScreenSize(udid)
        if (electronSize?.ok && electronSize.width && electronSize.height) {
          state.value.width = electronSize.width
          state.value.height = electronSize.height
          return
        }
      }
      const size = await getDeviceScreenSize(udid)
      state.value.width = size.width
      state.value.height = size.height
    } catch {
      state.value.width = nativeHost.value?.clientWidth ?? 0
      state.value.height = nativeHost.value?.clientHeight ?? 0
    }
  }

  async function waitForNativeHost(): Promise<HTMLElement | null> {
    for (let i = 0; i < 30; i++) {
      if (nativeHost.value) return nativeHost.value
      await new Promise(resolve => window.setTimeout(resolve, 50))
    }
    return nativeHost.value
  }

  function nativeHostRect(host: HTMLElement) {
    const rect = host.getBoundingClientRect()
    return {
      x: rect.left,
      y: rect.top,
      width: rect.width,
      height: rect.height,
      scaleFactor: window.devicePixelRatio || 1,
    }
  }

  function startNativeResizeSync() {
    stopNativeResizeSync()
    syncNativeResize()
    nativeResizeTimer = window.setInterval(() => {
      syncNativeResize()
    }, 500)
  }

  function stopNativeResizeSync() {
    if (nativeResizeTimer) {
      clearInterval(nativeResizeTimer)
      nativeResizeTimer = null
    }
    lastNativeRectKey = ''
  }

  function syncNativeResize() {
    if (!nativeHost.value || state.value.mode !== 'scrcpy-native') return
    const rect = nativeHostRect(nativeHost.value)
    const rectKey = `${Math.round(rect.x)}:${Math.round(rect.y)}:${Math.round(rect.width)}:${Math.round(rect.height)}:${rect.scaleFactor}`
    if (rectKey === lastNativeRectKey) return
    lastNativeRectKey = rectKey
    electronAPI?.scrcpyNativeResize?.(rect)
  }

  // ---- WebSocket mode (browser / fallback) ----

  function connectWebSocket(udid: string, options: ScreenStreamOptions) {
    const url = getDeviceScreenWebSocketUrl(udid, {
      platform: options.platform ?? 'android',
      provider: currentOptions.provider ?? 'auto',
      maxFps: currentOptions.maxFps,
      maxSize: currentOptions.maxSize,
      wdaUrl: options.wdaUrl,
      control: options.control,
    })

    const socket = new WebSocket(url)
    socket.binaryType = 'arraybuffer'
    ws.value = socket

    socket.onopen = () => {
      state.value.isConnected = true
      state.value.isLoading = false
      // Enable control as soon as the WebSocket is open — even ADB
      // fallback commands (tap/swipe/long_press) are sent via this
      // same WebSocket. The backend will send a 'control_mode' message
      // once scrcpy server startup completes, which upgrades us from
      // 'fallback' to 'live' (scrcpy native control).
      state.value.controlConnected = true
      state.value.controlMode = 'fallback'
      reconnectAttempts = 0
      startHeartbeat()
    }

    socket.onclose = (event) => {
      state.value.isConnected = false
      stopHeartbeat()
      stopFpsTimer()

      if (event.code !== 1000 && reconnectAttempts < maxReconnectAttempts) {
        reconnectAttempts++
        // Use a longer backoff on the last attempt — gives scrcpy server more
        // time to fully stop before reconnecting and avoids rapid open/close
        // cycles that cause "Unexpected ASGI message after websocket.close".
        const delay = reconnectAttempts >= maxReconnectAttempts
          ? 10000
          : 2000 * reconnectAttempts
        reconnectTimer = window.setTimeout(() => {
          connect(udid, options)
        }, delay)
      }
    }

    socket.onerror = () => {
      state.value.error = 'WebSocket 连接失败'
      state.value.isLoading = false
    }

    socket.onmessage = (event) => {
      if (typeof event.data === 'string') {
        try {
          const msg = JSON.parse(event.data)
          console.log('[ScreenStream] JSON msg:', msg.type, msg.provider || '', msg.mime_type || '', msg.mode || '')
          handleJsonMessage(msg)
        } catch {
          // ignore parse errors
        }
        return
      }

      // Binary frame
      state.value.frameCount++
      fpsCounter++
      state.value.isConnected = true
      state.value.isLoading = false

      const data = event.data as ArrayBuffer
      const isFirstFrame = state.value.frameCount <= 3
      if (isFirstFrame) {
        console.log('[ScreenStream] binary frame #' + state.value.frameCount,
          'size=' + data.byteLength,
          'provider=' + state.value.provider,
          'mimeType=' + state.value.mimeType,
          'hasDecoder=' + Boolean(decoder.value),
          'hasCanvas=' + Boolean(canvas.value))
      }
      // Detect H.264 by provider/mimeType OR by NAL start codes in the data.
      // Binary frames may arrive before the provider JSON message.
      const isH264 = (
        state.value.provider === 'scrcpy-h264' ||
        state.value.mimeType === 'video/h264' ||
        looksLikeH264(data)
      )
      if (isH264) {
        if (!decoder.value) {
          console.log('[ScreenStream] h264 frame but no decoder, trying initH264Decoder')
          initH264Decoder()
        }
        decoder.value?.feed(data)
        return
      }

      // Skip raw H.264 data that would produce a black image — only
      // drawImageFrame when we know the payload is an image format.
      if (state.value.mimeType && state.value.mimeType.startsWith('image/')) {
        drawImageFrame(data)
      }
    }
  }

  function handleJsonMessage(msg: Record<string, unknown>) {
    if (msg.type === 'provider') {
      state.value.provider = (msg.provider as string) ?? ''
      state.value.mimeType = (msg.mime_type as string) ?? ''
      state.value.notice = ''
      console.log('[ScreenStream] provider set:', state.value.provider, state.value.mimeType, 'hasCanvas=' + Boolean(canvas.value), 'hasDecoder=' + Boolean(decoder.value))
      if (msg.provider === 'scrcpy-h264' && !decoder.value) {
        // Only init if binary frames haven't already created a decoder
        initH264Decoder()
      }
    }

    if (msg.type === 'device_info') {
      state.value.width = (msg.screen_width as number) ?? 0
      state.value.height = (msg.screen_height as number) ?? 0
    }

    if (msg.type === 'control_mode') {
      const mode = (msg.mode as string) ?? 'adb_fallback'
      state.value.controlMode = mode === 'scrcpy' ? 'live' : 'fallback'
      state.value.controlConnected = true
    }

    if (msg.type === 'error') {
      state.value.error = (msg.message as string) || '投屏异常'
    }

    if (msg.type === 'control_error') {
      state.value.notice = `控制失败: ${(msg.message as string) || '设备控制命令执行失败'}`
    }

    if (msg.type === 'stream_idle') {
      state.value.notice = '投屏连接正常，等待新画面帧...'
    }
  }

  let lastImageCanvasW = 0
  let lastImageCanvasH = 0

  async function drawImageFrame(data: ArrayBuffer) {
    if (!canvas.value) return

    const blob = new Blob([data], { type: state.value.mimeType || 'image/jpeg' })
    const bitmap = await createImageBitmap(blob)
    const cvs = canvas.value
    const ctx = cvs.getContext('2d')
    if (!ctx) {
      bitmap.close()
      return
    }

    // Only resize canvas when dimensions actually change
    if (bitmap.width !== lastImageCanvasW || bitmap.height !== lastImageCanvasH) {
      cvs.width = bitmap.width
      cvs.height = bitmap.height
      lastImageCanvasW = bitmap.width
      lastImageCanvasH = bitmap.height
    }
    ctx.drawImage(bitmap, 0, 0)
    bitmap.close()
  }

  function initH264Decoder() {
    stopH264Decoder()
    if (!canvas.value) {
      // Canvas not rendered yet — flag for retry when setCanvas fires
      console.log('[ScreenStream] initH264Decoder skipped: no canvas yet')
      needsH264StreamRestartOnCanvasAttach = true
      return
    }

    try {
      console.log('[ScreenStream] creating H264 decoder, mode=webcodecs, canvas size=' + canvas.value.width + 'x' + canvas.value.height)
      const { decoder: dec, mode } = createH264Decoder(
        canvas.value,
        (message: string) => {
          console.warn('[ScreenStream] decoder warning:', message)
          state.value.notice = `解码警告: ${message}`
        },
        currentOptions.maxFps ?? DEFAULT_STREAM_MAX_FPS,
      )
      decoder.value = dec
      decoderMode.value = mode
      state.value.decoderMode = mode
      decoder.value.start()
      needsH264StreamRestartOnCanvasAttach = false
      console.log('[ScreenStream] H264 decoder created & started, mode=' + mode)
    } catch (error) {
      const message = error instanceof Error ? error.message : 'H.264 解码初始化失败'
      state.value.error = message
    }
  }

  function stopH264Decoder() {
    decoder.value?.close()
    decoder.value = null
  }

  function disconnect() {
    stopHeartbeat()
    stopFpsTimer()
    stopH264Decoder()
    stopQueuedWsMove()

    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }

    if (state.value.mode === 'scrcpy-window') {
      disconnectScrcpyWindow()
    } else if (state.value.mode === 'scrcpy-native') {
      disconnectScrcpyNative()
    } else if (state.value.mode === 'socketio') {
      disconnectSocketio()
    } else if (ws.value) {
      ws.value.onclose = null
      ws.value.onerror = null
      ws.value.onmessage = null
      ws.value.onopen = null
      if (ws.value.readyState === WebSocket.OPEN || ws.value.readyState === WebSocket.CONNECTING) {
        ws.value.close(1000, 'disconnect')
      }
      ws.value = null
    }

    state.value.udid = ''
    state.value.isConnected = false
    state.value.isLoading = false
    state.value.controlConnected = false
    state.value.controlMode = 'none'
  }

  function startHeartbeat() {
    stopHeartbeat()
    heartbeatTimer = window.setInterval(() => {
      if (ws.value?.readyState === WebSocket.OPEN) {
        ws.value.send(JSON.stringify({ type: 'ping' }))
      }
    }, 30000)
  }

  function stopHeartbeat() {
    if (heartbeatTimer) {
      clearInterval(heartbeatTimer)
      heartbeatTimer = null
    }
  }

  function startFpsTimer() {
    stopFpsTimer()
    fpsTimer = window.setInterval(() => {
      const now = performance.now()
      const elapsed = now - fpsLastTime
      if (elapsed > 0) {
        state.value.fps = Math.round((fpsCounter * 1000) / elapsed)
      }
      fpsCounter = 0
      fpsLastTime = now
    }, 1000)
  }

  function stopFpsTimer() {
    if (fpsTimer) {
      clearInterval(fpsTimer)
      fpsTimer = null
    }
  }

  function setCanvas(canvasEl: unknown) {
    const nextCanvas = canvasEl instanceof HTMLCanvasElement ? canvasEl : null
    if (canvas.value === nextCanvas) return

    const isH264Stream = (
      state.value.provider === 'scrcpy-h264' || state.value.mimeType === 'video/h264'
    )

    // Hot-swap: if decoder is alive and a new canvas is available,
    // just re-attach the decoder to the new canvas without tearing
    // down the WebSocket / decoder pipeline.
    if (decoder.value && nextCanvas && isH264Stream) {
      decoder.value.setCanvas(nextCanvas)
      needsH264StreamRestartOnCanvasAttach = false
      canvas.value = nextCanvas
      return
    }

    // Canvas removed (e.g. page unload) — keep decoder + WebSocket alive,
    // just flag that the next setCanvas needs to re-attach.
    if (decoder.value && !nextCanvas && isH264Stream) {
      needsH264StreamRestartOnCanvasAttach = true
      canvas.value = null
      return
    }

    if (decoder.value) {
      stopH264Decoder()
    }

    canvas.value = nextCanvas

    // Initialize decoder if canvas just became available for an active H.264 stream
    if (nextCanvas && state.value.isConnected && isH264Stream) {
      initH264Decoder()
      if (needsH264StreamRestartOnCanvasAttach) {
        restartH264StreamAfterCanvasAttach(nextCanvas)
      }
    }
  }

  function restartH264StreamAfterCanvasAttach(nextCanvas: HTMLCanvasElement) {
    if (!needsH264StreamRestartOnCanvasAttach || !state.value.udid) return
    needsH264StreamRestartOnCanvasAttach = false
    const udid = state.value.udid
    const options = { ...currentOptions }
    window.setTimeout(() => {
      if (canvas.value !== nextCanvas || state.value.udid !== udid) return
      connect(udid, options)
    }, 0)
  }

  function setNativeHost(hostEl: unknown) {
    nativeHost.value = hostEl instanceof HTMLElement ? hostEl : null
    if (nativeHost.value && state.value.mode === 'scrcpy-native' && state.value.isConnected) {
      syncNativeResize()
    }
  }

  function setVideo(videoElOrUnknown: unknown) {
    videoEl.value = videoElOrUnknown instanceof HTMLVideoElement ? videoElOrUnknown : null
    if (videoEl.value && state.value.isConnected) {
      // Try to set srcObject for video-based streams
      try {
        const existingStream = videoEl.value.srcObject as MediaStream | null
        if (!existingStream) {
          // Video stream is managed by the WebSocket provider
        }
      } catch { /* ignore */ }
    }
  }

  function setYumeHost(hostElOrUnknown: unknown) {
    yumeHost.value = hostElOrUnknown instanceof HTMLElement ? hostElOrUnknown : null
    if (yumeHost.value && state.value.isConnected) {
      // Yume (WebCodecs) decoder host is managed externally
    }
  }

  function hasLiveControl(): boolean {
    if (sioSocket.value?.connected) return true
    if (ws.value?.readyState === WebSocket.OPEN) return true
    // scrcpy-webcodecs: yumeHost with a canvas inside means control is available
    if (yumeHost.value?.querySelector('canvas')) return true
    return (
      state.value.isConnected &&
      (state.value.mode === 'scrcpy-native' || state.value.mode === 'scrcpy-window')
    )
  }

  function sendTouchDown(x: number, y: number): boolean {
    const preferApiTouchControl = currentOptions.preferApiTouchControl === true
    if (preferApiTouchControl && canUseApiControl()) {
      state.value.controlConnected = true
      state.value.controlMode = 'live'
      enqueueApiTouch(() => touchDown(state.value.udid, Math.round(x), Math.round(y), currentOptions.platform ?? 'android'))
      return true
    }
    if (sioSocket.value?.connected) {
      sioSocket.value.emit('touch_down', { x: Math.round(x), y: Math.round(y) })
      state.value.controlConnected = true
      state.value.controlMode = 'live'
      return true
    }
    if (ws.value?.readyState === WebSocket.OPEN) {
      stopQueuedWsMove()
      sendWsControl({ type: 'touch_down', x: Math.round(x), y: Math.round(y) })
      state.value.controlConnected = true
      state.value.controlMode = 'live'
      return true
    }
    if (canUseApiControl()) {
      state.value.controlConnected = true
      state.value.controlMode = 'live'
      enqueueApiTouch(() => touchDown(state.value.udid, Math.round(x), Math.round(y), currentOptions.platform ?? 'android'))
      return true
    }
    return false
  }

  function sendTouchMove(x: number, y: number) {
    const preferApiTouchControl = currentOptions.preferApiTouchControl === true
    if (preferApiTouchControl && canUseApiControl()) {
      queueApiTouchMove(Math.round(x), Math.round(y))
      return
    }
    if (sioSocket.value?.connected) {
      sioSocket.value.emit('touch_move', { x: Math.round(x), y: Math.round(y) })
      return
    }
    if (ws.value?.readyState === WebSocket.OPEN) {
      queueWsTouchMove(Math.round(x), Math.round(y))
      return
    }
    if (canUseApiControl()) {
      queueApiTouchMove(Math.round(x), Math.round(y))
    }
  }

  function sendTouchUp(x: number, y: number) {
    const preferApiTouchControl = currentOptions.preferApiTouchControl === true
    if (preferApiTouchControl && canUseApiControl()) {
      enqueueApiTouch(() => touchUp(state.value.udid, Math.round(x), Math.round(y), currentOptions.platform ?? 'android'))
      return
    }
    if (sioSocket.value?.connected) {
      sioSocket.value.emit('touch_up', { x: Math.round(x), y: Math.round(y) })
      return
    }
    if (ws.value?.readyState === WebSocket.OPEN) {
      flushQueuedWsMove()
      sendWsControl({ type: 'touch_up', x: Math.round(x), y: Math.round(y) })
      return
    }
    if (canUseApiControl()) {
      enqueueApiTouch(() => touchUp(state.value.udid, Math.round(x), Math.round(y), currentOptions.platform ?? 'android'))
    }
  }

  function sendControl(command: Record<string, unknown>) {
    if (currentOptions.preferApiTouchControl === true || state.value.mode === 'scrcpy-window' || state.value.mode === 'scrcpy-native') {
      void sendControlViaApi(command)
      return
    }
    if (sioSocket.value?.connected) {
      const cmdType = command.type as string
      sioSocket.value.emit(cmdType, command)
      return
    }
    if (ws.value?.readyState === WebSocket.OPEN) {
      sendWsControl(command)
    }
  }

  function sendWsControl(command: Record<string, unknown>): boolean {
    const socket = ws.value
    if (!socket || socket.readyState !== WebSocket.OPEN) return false
    if ((command.type === 'touch_move' || command.type === 'drag') && socket.bufferedAmount > 256 * 1024) {
      state.value.notice = '控制命令积压，已丢弃部分 MOVE 事件'
      return false
    }
    try {
      socket.send(JSON.stringify(command))
      return true
    } catch (error) {
      reportControlError(error)
      return false
    }
  }

  function queueWsTouchMove(x: number, y: number) {
    latestWsMove = { x, y }
    if (wsMoveFrame !== null) return
    wsMoveFrame = window.requestAnimationFrame(() => {
      wsMoveFrame = null
      flushQueuedWsMove()
    })
  }

  function flushQueuedWsMove() {
    if (!latestWsMove) return
    const point = latestWsMove
    latestWsMove = null
    sendWsControl({ type: 'touch_move', x: point.x, y: point.y })
  }

  function stopQueuedWsMove() {
    latestWsMove = null
    if (wsMoveFrame !== null) {
      window.cancelAnimationFrame(wsMoveFrame)
      wsMoveFrame = null
    }
  }

  async function sendControlViaApi(command: Record<string, unknown>) {
    const udid = state.value.udid
    if (!udid) return

    const cmdType = command.type
    try {
      if (cmdType === 'tap') {
        await tapDevicePoint(udid, {
          x: command.x as number,
          y: command.y as number,
          platform: currentOptions.platform ?? 'android',
        })
        return
      }

      if (cmdType === 'key') {
        await pressDeviceKey(udid, command.keycode as number)
        return
      }

      if (cmdType === 'swipe') {
        await swipeDevice(
          udid,
          command.x1 as number,
          command.y1 as number,
          command.x2 as number,
          command.y2 as number,
          (command.duration_ms as number) ?? 300,
          currentOptions.platform ?? 'android',
        )
        return
      }

      if (cmdType === 'long_press') {
        await swipeDevice(
          udid,
          command.x as number,
          command.y as number,
          command.x as number,
          command.y as number,
          (command.duration_ms as number) ?? 800,
          currentOptions.platform ?? 'android',
        )
        return
      }

      if (cmdType === 'text') {
        await inputDeviceText(udid, command.text as string)
        return
      }

      if (cmdType === 'drag') {
        await swipeDevice(
          udid,
          command.x1 as number,
          command.y1 as number,
          command.x2 as number,
          command.y2 as number,
          (command.drag_duration_ms as number) ?? 300,
          currentOptions.platform ?? 'android',
        )
      }
    } catch (error) {
      reportControlError(error)
    }
  }

  function canUseApiControl(): boolean {
    return Boolean(
      state.value.udid &&
      state.value.isConnected &&
      (
        state.value.mode === 'scrcpy-native' ||
        state.value.mode === 'scrcpy-window' ||
        currentOptions.preferApiTouchControl === true
      ),
    )
  }

  function enqueueApiTouch(task: () => Promise<unknown>) {
    apiTouchChain = apiTouchChain
      .catch(() => undefined)
      .then(async () => {
        await task()
      })
      .catch((error) => {
        reportControlError(error)
      })
  }

  function queueApiTouchMove(x: number, y: number) {
    latestApiMove = { x, y }
    if (apiMoveRunning) return
    apiMoveRunning = true
    enqueueApiTouch(async () => {
      try {
        while (latestApiMove) {
          const point = latestApiMove
          latestApiMove = null
          await touchMove(state.value.udid, point.x, point.y, currentOptions.platform ?? 'android')
        }
      } finally {
        apiMoveRunning = false
      }
    })
  }

  function reportControlError(error: unknown) {
    const message = error instanceof Error ? error.message : String(error || '设备控制失败')
    state.value.notice = `控制失败: ${message}`
    state.value.controlMode = 'fallback'
  }

  function toDevicePoint(event: PointerEvent): { x: number; y: number } | null {
    // Priority: canvas > video > yumeHost inner canvas > nativeHost
    // When scrcpy-webcodecs is used, the video is rendered inside yumeHost
    // as a child canvas, so we must query into yumeHost to find it.
    const target = canvas.value
      ?? videoEl.value
      ?? (yumeHost.value?.querySelector('canvas') as HTMLElement | null)
      ?? nativeHost.value
    if (!target) return null
    const rect = target.getBoundingClientRect()
    if (rect.width <= 0 || rect.height <= 0) return null

    const targetWidth = state.value.width || target.clientWidth
    const targetHeight = state.value.height || target.clientHeight
    const x = ((event.clientX - rect.left) / rect.width) * targetWidth
    const y = ((event.clientY - rect.top) / rect.height) * targetHeight
    return {
      x: Math.max(0, Math.min(targetWidth, x)),
      y: Math.max(0, Math.min(targetHeight, y)),
    }
  }

  function sendKey(keyCode: number) {
    sendControl({ type: 'key', keycode: keyCode })
  }

  function sendDrag(
    x1: number,
    y1: number,
    x2: number,
    y2: number,
    options?: { pressDurationMs?: number; dragDurationMs?: number }
  ) {
    sendControl({
      type: 'drag',
      x1,
      y1,
      x2,
      y2,
      press_duration_ms: options?.pressDurationMs ?? 200,
      drag_duration_ms: options?.dragDurationMs ?? 300,
    })
  }

  onUnmounted(() => {
    disconnect()
  })

  return {
    ws,
    state,
    canvas,
    nativeHost,
    videoEl,
    yumeHost,
    decoderMode,
    connect,
    disconnect,
    setCanvas,
    setNativeHost,
    setVideo,
    setYumeHost,
    hasLiveControl,
    sendTouchDown,
    sendTouchMove,
    sendTouchUp,
    sendControl,
    toDevicePoint,
    sendKey,
    sendDrag,
  }
}
