/**
 * Socket.IO scrcpy stream — legacy/compatibility path.
 *
 * This stream uses the Socket.IO transport which runs scrcpy CLI with
 * --no-control. Control commands fall back to ADB motionevent which
 * has higher latency (~50-100ms per event) than scrcpy native control.
 *
 * For real-time control, prefer useScreenStream (WebSocket path) which
 * uses ScrcpyH264StreamSession with control=true and provides
 * scrcpy native control (~1-5ms per event).
 *
 * Use this composable only when:
 * - WebSocket H.264 stream is not available
 * - You need Socket.IO for a specific integration
 */
import { ref, computed, onUnmounted } from 'vue'
import { io, Socket } from 'socket.io-client'
import { locateDeviceUiElement, type DeviceUiLocateResponse } from '../api'

const SOCKET_IO_URL = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000'

export interface ScrcpyMetadata {
  deviceName: string
  width: number
  height: number
  codec: number | string
  platform?: string
}

export interface ScrcpyStreamState {
  udid: string
  isConnected: boolean
  isLoading: boolean
  error: string
  notice: string
  fps: number
  decodeFps: number
  provider: string
  width: number
  height: number
  controlConnected: boolean
  controlMode: 'scrcpy' | 'adb_fallback' | 'none'
  platform: string
}

const MOVE_THROTTLE_MS = 16

export function useScrcpyStream() {
  const socketRef = ref<Socket | null>(null)
  const canvasRef = ref<HTMLCanvasElement | null>(null)
  const state = ref<ScrcpyStreamState>({
    udid: '',
    isConnected: false,
    isLoading: false,
    error: '',
    notice: '',
    fps: 0,
    decodeFps: 0,
    provider: '',
    width: 0,
    height: 0,
    controlConnected: false,
    controlMode: 'none' as const,
    platform: 'android',
  })

  // WebCodecs decoder state
  let decoder: VideoDecoder | null = null
  let spsData: Uint8Array | null = null
  let ppsData: Uint8Array | null = null
  let timestamp = 0
  let frameIntervalUs = 33_333
  let codecDescription: Uint8Array | null = null  // AVCC codec description from SPS/PPS

  // FPS counters (recv from network vs decoded and rendered)
  let fpsCounter = 0
  let decodeFpsCounter = 0
  let fpsLastTime = performance.now()
  let fpsTimer: number | null = null

  // Touch throttle
  let lastMoveTime = 0

  // NAL buffer for parsing
  let nalBuffer: Uint8Array<ArrayBuffer> = new Uint8Array()

  const isIos = computed(() => state.value.platform === 'ios')

  function connect(udid: string, options: { maxFps?: number; maxSize?: number; bitRate?: number; platform?: string } = {}) {
    disconnect()
    state.value.udid = udid
    state.value.isLoading = true
    state.value.error = ''
    state.value.notice = ''
    state.value.fps = 0
    state.value.provider = ''
    state.value.width = 0
    state.value.height = 0
    state.value.platform = options.platform ?? 'android'
    state.value.controlMode = 'none'
    state.value.controlConnected = false

    fpsCounter = 0
    decodeFpsCounter = 0
    fpsLastTime = performance.now()
    startFpsTimer()
    nalBuffer = new Uint8Array()
    spsData = null
    ppsData = null
    codecDescription = null

    const socket = io(SOCKET_IO_URL, {
      path: '/socket.io',
      transports: ['websocket'],
    })
    socketRef.value = socket

    socket.on('connect', () => {
      state.value.isConnected = true
      state.value.isLoading = false
      socket.emit('connect-device', {
        device_id: udid,
        deviceId: udid,
        maxSize: options.maxSize ?? 720,
        bitRate: options.bitRate ?? 2_000_000,
        maxFps: options.maxFps ?? 30,
        platform: state.value.platform,
      })
    })

    socket.on('video-metadata', (meta: ScrcpyMetadata) => {
      state.value.width = meta.width
      state.value.height = meta.height
      state.value.provider = state.value.platform === 'ios' ? 'ios-socketio' : 'scrcpy-socketio'
      if (meta.platform) {
        state.value.platform = meta.platform
      }
      console.log('[ScrcpyStream] video-metadata:', meta.width, 'x', meta.height, 'codec:', meta.codec, 'platform:', meta.platform)
      if (state.value.platform !== 'ios') {
        initDecoder(meta)
      }
    })

    socket.on('video-data', (packet: any) => {
      fpsCounter++
      state.value.isConnected = true
      state.value.isLoading = false

      // Handle different data formats from Socket.IO
      const platform = packet.platform || state.value.platform
      const dataType = packet.type
      const encoding = packet.encoding

      // Extract raw bytes from the packet
      let rawData: Uint8Array

      if (encoding === 'base64' && typeof packet.data === 'string') {
        // Preferred: base64 encoded (most reliable across Socket.IO configs)
        const binary = atob(packet.data)
        rawData = new Uint8Array(binary.length)
        for (let i = 0; i < binary.length; i++) rawData[i] = binary.charCodeAt(i)
      } else if (packet.data instanceof ArrayBuffer) {
        rawData = new Uint8Array(packet.data)
      } else if (packet.data instanceof Uint8Array) {
        rawData = new Uint8Array(packet.data)
      } else if (typeof packet.data === 'object' && packet.data?.type === 'Buffer' && Array.isArray(packet.data.data)) {
        // Socket.IO v5 serializes Python bytes as {type: "Buffer", data: [int, ...]}
        rawData = new Uint8Array(packet.data.data)
      } else if (typeof packet.data === 'string') {
        // Assume base64 if string without explicit encoding
        const binary = atob(packet.data)
        rawData = new Uint8Array(binary.length)
        for (let i = 0; i < binary.length; i++) rawData[i] = binary.charCodeAt(i)
      } else {
        console.warn('[ScrcpyStream] Unknown frame data format:', typeof packet.data, packet.data)
        return
      }

      if (rawData.length === 0) return

      if (platform === 'ios' || dataType === 'jpeg') {
        feedIosFrame(toArrayBuffer(rawData))
      } else {
        feedDecoder(rawData)
      }
    })

    socket.on('error', (error: { message?: string; type?: string }) => {
      state.value.error = error?.message || 'Socket.IO 连接错误'
      state.value.isLoading = false
      console.error('[ScrcpyStream] Error:', error)
    })

    socket.on('control-error', (error: { message?: string; action?: string }) => {
      state.value.notice = `控制失败: ${error?.message || error?.action || '设备控制命令执行失败'}`
      console.error('[ScrcpyStream] Control error:', error)
    })

    socket.on('control-mode', (info: { mode: string; device_id?: string }) => {
      state.value.controlMode = (info.mode === 'scrcpy' ? 'scrcpy' : 'adb_fallback') as 'scrcpy' | 'adb_fallback'
      state.value.controlConnected = info.mode === 'scrcpy'
      console.log('[ScrcpyStream] Control mode:', info.mode)
    })

    socket.on('disconnect', (reason) => {
      state.value.isConnected = false
      stopDecoder()
      console.log('[ScrcpyStream] Disconnected:', reason)
    })
  }

  // ── WebCodecs decoder (Android H.264) ──────────────────────────────

  function initDecoder(_meta: ScrcpyMetadata) {
    stopDecoder()
    if (!canvasRef.value) {
      console.warn('[ScrcpyStream] No canvas for decoder init')
      return
    }
    if (typeof VideoDecoder === 'undefined') {
      state.value.error = '当前浏览器不支持 WebCodecs VideoDecoder'
      return
    }

    const canvas = canvasRef.value
    // Set canvas size from metadata
    if (_meta.width && _meta.height) {
      canvas.width = _meta.width
      canvas.height = _meta.height
    }
    const context = canvas.getContext('2d')
    if (!context) return

    decoder = new VideoDecoder({
      output: (frame: VideoFrame) => {
        const c = canvasRef.value
        if (!c) { frame.close(); return }
        const ctx = c.getContext('2d')
        if (!ctx) { frame.close(); return }

        if (c.width !== frame.displayWidth || c.height !== frame.displayHeight) {
          c.width = frame.displayWidth
          c.height = frame.displayHeight
        }
        ctx.drawImage(frame as unknown as CanvasImageSource, 0, 0)
        decodeFpsCounter++
        frame.close()
      },
      error: (e: Error) => {
        console.error('[ScrcpyStream] Decoder error:', e.message)
        if (decoder && decoder.state !== 'closed') {
          try { decoder.close() } catch { /* ignore */ }
          decoder = null
          // Don't auto-recreate on every error, wait for next keyframe
        }
      },
    })

    // Use a more permissive codec string — covers Baseline, Main, High profiles
    try {
      decoder.configure({
        codec: 'avc1.42E01F',
        optimizeForLatency: true,
      })
      console.log('[ScrcpyStream] WebCodecs decoder configured')
    } catch (e: any) {
      console.error('[ScrcpyStream] Decoder configure failed:', e.message)
      // Try alternate codec string for High Profile
      try {
        decoder.configure({
          codec: 'avc1.64001F',
          optimizeForLatency: true,
        })
      } catch (e2: any) {
        console.error('[ScrcpyStream] Alternate codec also failed:', e2.message)
        state.value.error = 'WebCodecs 解码器配置失败: ' + e.message
      }
    }
  }

  function ensureDecoder() {
    if (decoder && decoder.state !== 'closed') return true
    if (!canvasRef.value || !state.value.width) return false
    if (typeof VideoDecoder === 'undefined') return false

    const canvas = canvasRef.value
    const context = canvas.getContext('2d')
    if (!context) return false

    decoder = new VideoDecoder({
      output: (frame: VideoFrame) => {
        const c = canvasRef.value
        if (!c) { frame.close(); return }
        const ctx = c.getContext('2d')
        if (!ctx) { frame.close(); return }
        if (c.width !== frame.displayWidth || c.height !== frame.displayHeight) {
          c.width = frame.displayWidth
          c.height = frame.displayHeight
        }
        ctx.drawImage(frame as unknown as CanvasImageSource, 0, 0)
        frame.close()
      },
      error: (e: Error) => {
        console.error('[ScrcpyStream] Decoder error (recreated):', e.message)
        if (decoder && decoder.state !== 'closed') {
          try { decoder.close() } catch { /* ignore */ }
          decoder = null
        }
      },
    })

    try {
      decoder.configure({ codec: 'avc1.42E01F', optimizeForLatency: true })
      return true
    } catch {
      return false
    }
  }

  function feedDecoder(data: Uint8Array) {
    if (!ensureDecoder()) {
      // Buffer NAL data until decoder is ready
      nalBuffer = concatBytes([nalBuffer, data])
      return
    }

    // Append to NAL buffer and extract units
    nalBuffer = concatBytes([nalBuffer, data])
    const nalUnits = extractNalUnits(nalBuffer)
    if (nalUnits.length === 0) return

    // Reset buffer after extraction
    nalBuffer = new Uint8Array()

    for (const nalUnit of nalUnits) {
      if (nalUnit.length < 2) continue

      const nalType = getNalType(nalUnit)

      // SPS (7) and PPS (8) — store and build codec description
      if (nalType === 7) {
        spsData = nalUnit
        codecDescription = null  // Force rebuild
        continue
      }
      if (nalType === 8) {
        ppsData = nalUnit
        codecDescription = null
        continue
      }

      // Only process IDR (5) and non-IDR (1) slices
      if (nalType !== 1 && nalType !== 5) continue

      const isKeyframe = nalType === 5

      // Skip delta frames if decoder queue is too long (prevents latency buildup)
      if (!isKeyframe && (decoder!.decodeQueueSize ?? 0) > 3) continue

      // For keyframes, prepend SPS+PPS
      let frameData: Uint8Array
      if (isKeyframe && spsData && ppsData) {
        frameData = concatBytes([spsData, ppsData, nalUnit])
        // Build AVCC codec description for the first keyframe
        if (!codecDescription) {
          codecDescription = buildAvccDescription(spsData, ppsData)
        }
      } else {
        frameData = nalUnit
      }

      try {
        // If we have a codec description and this is the first keyframe,
        // reconfigure the decoder with the description
        if (isKeyframe && codecDescription && decoder!.state === 'configured') {
          try {
            decoder!.configure({
              codec: 'avc1.42E01F',
              optimizeForLatency: true,
              description: codecDescription,
            })
            codecDescription = null  // Only apply once
          } catch {
            // If reconfigure fails, just continue with current config
          }
        }

        decoder!.decode(new EncodedVideoChunk({
          type: isKeyframe ? 'key' : 'delta',
          timestamp,
          data: frameData,
        }))
        timestamp += frameIntervalUs
      } catch (e: any) {
        console.error('[ScrcpyStream] Decode error:', e.message, 'nalType:', nalType, 'size:', frameData.length)
        if (decoder && decoder.state !== 'closed') {
          try { decoder.close() } catch { /* ignore */ }
          decoder = null
        }
        // On decode error, reset and wait for next keyframe
        nalBuffer = new Uint8Array()
      }
    }
  }

  function stopDecoder() {
    if (decoder && decoder.state !== 'closed') {
      try { decoder.close() } catch { /* ignore */ }
    }
    decoder = null
    spsData = null
    ppsData = null
    codecDescription = null
    timestamp = 0
  }

  // ── iOS JPEG frame renderer ────────────────────────────────────────

  async function feedIosFrame(data: ArrayBuffer) {
    const canvas = canvasRef.value
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    try {
      const blob = new Blob([data], { type: 'image/jpeg' })
      const bitmap = await createImageBitmap(blob)
      if (canvas.width !== bitmap.width || canvas.height !== bitmap.height) {
        canvas.width = bitmap.width
        canvas.height = bitmap.height
      }
      ctx.drawImage(bitmap, 0, 0)
      bitmap.close()
    } catch (e: any) {
      console.error('[ScrcpyStream] iOS frame render error:', e.message)
    }
  }

  // ── NAL parsing ────────────────────────────────────────────────────

  function extractNalUnits(data: Uint8Array): Uint8Array[] {
    const starts = findStartCodes(data)
    if (starts.length < 2) return []

    const units: Uint8Array[] = []
    for (let i = 0; i < starts.length - 1; i++) {
      const unit = data.slice(starts[i], starts[i + 1])
      if (unit.length > 0) units.push(unit)
    }
    return units
  }

  function findStartCodes(data: Uint8Array): number[] {
    const starts: number[] = []
    const len = data.length
    for (let i = 0; i < len - 3; i++) {
      if (data[i] === 0 && data[i + 1] === 0 && data[i + 2] === 1) {
        starts.push(i)
        i += 2
      } else if (i < len - 3 && data[i] === 0 && data[i + 1] === 0 && data[i + 2] === 0 && data[i + 3] === 1) {
        starts.push(i)
        i += 3
      }
    }
    return starts
  }

  function getNalType(nalUnit: Uint8Array): number {
    // Find the NAL header byte after the start code
    // Start code is 00 00 01 (3 bytes) or 00 00 00 01 (4 bytes)
    let offset = 0
    if (nalUnit.length >= 4 && nalUnit[2] === 0 && nalUnit[3] === 1) {
      offset = 4
    } else if (nalUnit.length >= 3 && nalUnit[1] === 0 && nalUnit[2] === 1) {
      offset = 3
    } else {
      return 0
    }
    if (offset >= nalUnit.length) return 0
    return nalUnit[offset] & 0x1f
  }

  function concatBytes(chunks: Uint8Array[]): Uint8Array<ArrayBuffer> {
    const length = chunks.reduce((sum, c) => sum + c.length, 0)
    const result = new Uint8Array(length)
    let offset = 0
    for (const c of chunks) {
      result.set(c, offset)
      offset += c.length
    }
    return result
  }

  function toArrayBuffer(data: Uint8Array): ArrayBuffer {
    return data.buffer.slice(data.byteOffset, data.byteOffset + data.byteLength) as ArrayBuffer
  }

  /**
   * Build AVCC codec description from SPS and PPS NAL units.
   * This is needed for WebCodecs to properly configure the decoder
   * with the correct profile/level information.
   *
   * AVCC format:
   *   version (1) = 1
   *   profile (1) = from SPS
   *   compatibility (1) = from SPS
   *   level (1) = from SPS
   *   lengthSizeMinusOne (1) = 0xFF (4-byte NAL length)
   *   numOfSPS (1) = 0xE1 (1 SPS)
   *   spsLength (2)
   *   spsData (without start code)
   *   numOfPPS (1) = 1
   *   ppsLength (2)
   *   ppsData (without start code)
   */
  function buildAvccDescription(sps: Uint8Array, pps: Uint8Array): Uint8Array {
    // Strip start codes from SPS and PPS
    const spsNoStart = stripStartCode(sps)
    const ppsNoStart = stripStartCode(pps)

    const totalLen = 6 + 2 + spsNoStart.length + 1 + 2 + ppsNoStart.length
    const result = new Uint8Array(totalLen)
    let offset = 0

    // version
    result[offset++] = 1
    // profile (first byte after start code in SPS)
    result[offset++] = spsNoStart[0]
    // compatibility
    result[offset++] = spsNoStart[1]
    // level
    result[offset++] = spsNoStart[2]
    // lengthSizeMinusOne with reserved bits
    result[offset++] = 0xFF
    // numOfSPS with reserved bits
    result[offset++] = 0xE1
    // SPS length (big-endian)
    result[offset++] = (spsNoStart.length >> 8) & 0xFF
    result[offset++] = spsNoStart.length & 0xFF
    // SPS data
    result.set(spsNoStart, offset)
    offset += spsNoStart.length
    // numOfPPS
    result[offset++] = 1
    // PPS length (big-endian)
    result[offset++] = (ppsNoStart.length >> 8) & 0xFF
    result[offset++] = ppsNoStart.length & 0xFF
    // PPS data
    result.set(ppsNoStart, offset)

    return result
  }

  function stripStartCode(nal: Uint8Array): Uint8Array {
    // Strip 3 or 4 byte start code
    if (nal.length >= 4 && nal[0] === 0 && nal[1] === 0 && nal[2] === 0 && nal[3] === 1) {
      return nal.slice(4)
    }
    if (nal.length >= 3 && nal[0] === 0 && nal[1] === 0 && nal[2] === 1) {
      return nal.slice(3)
    }
    return nal
  }

  // ── Control methods ────────────────────────────────────────────────

  function sendControl(action: string, params: Record<string, unknown>) {
    socketRef.value?.emit('control-action', {
      device_id: state.value.udid,
      deviceId: state.value.udid,
      action,
      params,
      platform: state.value.platform,
    })
  }

  function touchDown(x: number, y: number) {
    sendControl('touch_down', { x, y })
    state.value.controlConnected = true
  }

  function touchMove(x: number, y: number) {
    const now = Date.now()
    if (now - lastMoveTime < MOVE_THROTTLE_MS) return
    lastMoveTime = now
    sendControl('touch_move', { x, y })
  }

  function touchUp(x: number, y: number) {
    sendControl('touch_up', { x, y })
  }

  function tap(x: number, y: number) {
    sendControl('tap', { x, y })
  }

  function swipe(x1: number, y1: number, x2: number, y2: number, duration = 300) {
    sendControl('swipe', { x1, y1, x2, y2, duration })
  }

  function longPress(x: number, y: number, duration = 800) {
    sendControl('long_press', { x, y, duration })
  }

  function key(keycode: number) {
    sendControl('key', { keycode })
  }

  function text(t: string) {
    sendControl('text', { text: t })
  }

  // ── Coordinate mapping ─────────────────────────────────────────────

  function canvasToDevice(clientX: number, clientY: number): { x: number; y: number } {
    const canvas = canvasRef.value
    if (!canvas || !state.value.width) return { x: 0, y: 0 }
    const rect = canvas.getBoundingClientRect()
    const x = Math.round(((clientX - rect.left) / rect.width) * state.value.width)
    const y = Math.round(((clientY - rect.top) / rect.height) * state.value.height)
    return {
      x: Math.max(0, Math.min(state.value.width, x)),
      y: Math.max(0, Math.min(state.value.height, y)),
    }
  }

  // ── Element info query (for script recording) ──────────────────────

  async function queryElementInfo(x: number, y: number): Promise<DeviceUiLocateResponse | null> {
    try {
      return await locateDeviceUiElement(state.value.udid, { x, y, platform: state.value.platform })
    } catch {
      return null
    }
  }

  // ── FPS timer ──────────────────────────────────────────────────────

  function startFpsTimer() {
    stopFpsTimer()
    fpsTimer = window.setInterval(() => {
      const now = performance.now()
      const elapsed = now - fpsLastTime
      if (elapsed > 0) {
        state.value.fps = Math.round((fpsCounter * 1000) / elapsed)
        state.value.decodeFps = Math.round((decodeFpsCounter * 1000) / elapsed)
      }
      fpsCounter = 0
      decodeFpsCounter = 0
      fpsLastTime = now
    }, 1000)
  }

  function stopFpsTimer() {
    if (fpsTimer) {
      clearInterval(fpsTimer)
      fpsTimer = null
    }
  }

  function disconnect() {
    stopDecoder()
    stopFpsTimer()
    if (socketRef.value) {
      socketRef.value.emit('disconnect-device', { device_id: state.value.udid })
      socketRef.value.disconnect()
      socketRef.value = null
    }
    state.value.udid = ''
    state.value.isConnected = false
    state.value.isLoading = false
    state.value.controlConnected = false
    state.value.controlMode = 'none'
  }

  function setCanvas(canvasEl: unknown) {
    canvasRef.value = canvasEl instanceof HTMLCanvasElement ? canvasEl : null
  }

  function hasLiveControl(): boolean {
    return state.value.controlConnected
  }

  onUnmounted(() => {
    disconnect()
  })

  return {
    state,
    canvasRef,
    isIos,
    connect,
    disconnect,
    setCanvas,
    hasLiveControl,
    touchDown,
    touchMove,
    touchUp,
    tap,
    swipe,
    longPress,
    key,
    text,
    canvasToDevice,
    queryElementInfo,
  }
}
