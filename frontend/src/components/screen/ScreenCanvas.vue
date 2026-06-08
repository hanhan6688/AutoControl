<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import { createH264Decoder } from '../../h264Decoder'
import type { H264DecoderLike, DecoderMode } from '../../h264Decoder'

const props = defineProps<{
  wsUrl: string
  maxWidth?: number
  maxHeight?: number
}>()

const emit = defineEmits<{
  connected: []
  disconnected: []
  error: [message: string]
  frame: [count: number]
}>()

const canvasRef = ref<HTMLCanvasElement | null>(null)
const ws = ref<WebSocket | null>(null)
const isConnected = ref(false)
const frameCount = ref(0)
const fps = ref(0)
const screenError = ref('')
const h264Decoder = ref<H264DecoderLike | null>(null)
const decoderMode = ref<DecoderMode>('webcodecs')

let fpsCounter = 0
let fpsLastTime = 0
let fpsTimer: number | null = null

function connect() {
  if (ws.value?.readyState === WebSocket.OPEN) return

  ws.value = new WebSocket(props.wsUrl)
  ws.value.binaryType = 'arraybuffer'

  ws.value.onopen = () => {
    isConnected.value = true
    screenError.value = ''
    emit('connected')
    startFpsTimer()
  }

  ws.value.onclose = () => {
    isConnected.value = false
    emit('disconnected')
    stopFpsTimer()
  }

  ws.value.onerror = () => {
    screenError.value = '连接失败'
    emit('error', '连接失败')
  }

  ws.value.onmessage = (event) => {
    if (typeof event.data === 'string') {
      const msg = JSON.parse(event.data)
      if (msg.type === 'provider') {
        initDecoder()
      }
    } else if (event.data instanceof ArrayBuffer) {
      decodeFrame(event.data)
    }
  }
}

function initDecoder() {
    if (!canvasRef.value) return
    try {
      const { decoder: dec, mode } = createH264Decoder(
        canvasRef.value,
        (msg: string) => { screenError.value = msg },
        fps.value || 60,
      )
      h264Decoder.value = dec
      decoderMode.value = mode
      h264Decoder.value.start()
    } catch (exc) {
      screenError.value = `解码器初始化失败: ${exc}`
    }
  }

function decodeFrame(data: ArrayBuffer) {
  if (!h264Decoder.value) return
  h264Decoder.value.feed(data)
  frameCount.value++
  fpsCounter++
  emit('frame', frameCount.value)
}

function startFpsTimer() {
  stopFpsTimer()
  fpsCounter = 0
  fpsLastTime = performance.now()
  fpsTimer = window.setInterval(() => {
    const now = performance.now()
    const elapsed = now - fpsLastTime
    if (elapsed > 0) {
      fps.value = Math.round((fpsCounter * 1000) / elapsed)
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

function disconnect() {
  if (ws.value) {
    ws.value.close()
    ws.value = null
  }
  isConnected.value = false
  stopFpsTimer()
}

watch(() => props.wsUrl, (newUrl) => {
  if (newUrl) {
    disconnect()
    connect()
  }
})

onMounted(() => {
  if (props.wsUrl) connect()
})

onUnmounted(() => {
  disconnect()
})

defineExpose({
  connect,
  disconnect,
  isConnected,
  frameCount,
})
</script>

<template>
  <div class="screen-canvas">
    <div v-if="screenError" class="screen-canvas__error">
      {{ screenError }}
    </div>
    <canvas
      ref="canvasRef"
      class="screen-canvas__canvas"
      :style="{ maxWidth: maxWidth ? `${maxWidth}px` : '100%' }"
    />
    <div v-if="isConnected" class="screen-canvas__status">
      <el-tag type="success" size="small">已连接</el-tag>
      <span class="frame-count">{{ fps }} fps</span>
      <el-tag v-if="decoderMode === 'mse'" type="warning" size="small">MSE</el-tag>
    </div>
  </div>
</template>

<style scoped>
.screen-canvas {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #000;
  border-radius: 8px;
  overflow: hidden;
}

.screen-canvas__canvas {
  display: block;
  max-width: 100%;
  max-height: 100%;
}

.screen-canvas__error {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  color: var(--el-color-danger);
  font-size: 14px;
}

.screen-canvas__status {
  position: absolute;
  top: 8px;
  right: 8px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.frame-count {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.7);
}
</style>
