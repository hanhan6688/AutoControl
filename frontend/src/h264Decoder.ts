type EncodedVideoChunkType = 'key' | 'delta'
type Bytes = Uint8Array<ArrayBufferLike>

interface VideoDecoderLike {
  state: string
  decodeQueueSize?: number
  configure(config: Record<string, unknown>): void
  decode(chunk: unknown): void
  flush(): Promise<void>
  close(): void
}

declare const VideoDecoder: {
  new (init: { output: (frame: VideoFrame) => void; error: (error: Error) => void }): VideoDecoderLike
  isConfigSupported?: (config: Record<string, unknown>) => Promise<{ supported?: boolean }>
}

declare const EncodedVideoChunk: {
  new (init: { type: EncodedVideoChunkType; timestamp: number; data: Uint8Array }): unknown
}

interface VideoFrame {
  displayWidth: number
  displayHeight: number
  close(): void
}

import type { H264DecoderLike, DecoderMode } from './h264MseDecoder'
import { H264MseDecoder } from './h264MseDecoder'
export type { DecoderMode, H264DecoderLike }

interface PendingSlice {
  isKey: boolean
  timestamp: number
  data: Bytes
}

export class H264CanvasDecoder {
  private decoder: VideoDecoderLike | null = null
  private buffer: Bytes = new Uint8Array(0)
  private timestamp = 0
  private sps: Bytes | null = null
  private pps: Bytes | null = null
  private configured = false
  private pendingSlices: PendingSlice[] = []
  private context: CanvasRenderingContext2D
  private frameIntervalUs: number = 16_667

  constructor(
    private canvas: HTMLCanvasElement,
    private readonly onError: (message: string) => void,
    private readonly targetFps: number = 60,
  ) {
    const context = canvas.getContext('2d')
    if (!context) {
      throw new Error('Canvas 2D context is not available')
    }
    this.context = context
    this._firstFrameLogged = false
    this.frameIntervalUs = Math.round(1_000_000 / Math.max(1, targetFps))
  }

  static isSupported() {
    return typeof VideoDecoder !== 'undefined' && typeof EncodedVideoChunk !== 'undefined'
  }

  private _firstFrameLogged = false
  private _keyFrameCount = 0
  private _canvasW = 0
  private _canvasH = 0

  setCanvas(canvas: HTMLCanvasElement): void {
    this.canvas = canvas
    const ctx = canvas.getContext('2d')
    if (ctx) this.context = ctx
    this._canvasW = 0
    this._canvasH = 0
  }

  start() {
    if (!H264CanvasDecoder.isSupported()) {
      throw new Error('当前浏览器不支持 WebCodecs VideoDecoder')
    }

    this._firstFrameLogged = false
    this.decoder = this.makeDecoder(() => {
      console.warn('[H264Decoder] decoder error, trying recreate. sps=' + Boolean(this.sps) + ' pps=' + Boolean(this.pps))
      if (this.sps && this.pps) {
        try { this.recreateDecoder() } catch {}
      }
    })
    console.log('[H264Decoder] decoder created (not yet configured — waiting for SPS+PPS)')
  }

  private makeDecoder(onError?: () => void): VideoDecoderLike {
    return new VideoDecoder({
      output: (frame) => {
        if (!this._firstFrameLogged) {
          this._firstFrameLogged = true
          console.log('[H264Decoder] FIRST FRAME OUTPUT!', frame.displayWidth + 'x' + frame.displayHeight)
        }
        // Only resize canvas when dimensions actually change — avoids
        // clearing the canvas buffer every frame (expensive re-allocation).
        const fw = frame.displayWidth
        const fh = frame.displayHeight
        if (fw !== this._canvasW || fh !== this._canvasH) {
          this.canvas.width = fw
          this.canvas.height = fh
          this._canvasW = fw
          this._canvasH = fh
        }
        this.context.drawImage(frame as unknown as CanvasImageSource, 0, 0)
        frame.close()
      },
      error: (e) => {
        console.warn('[H264Decoder] VideoDecoder error:', e)
        if (this.decoder && this.decoder.state !== 'closed') {
          try { this.decoder.close() } catch {}
          this.decoder = null
          onError?.()
        }
      },
    })
  }

  private configureWithCurrentSpsPps(): boolean {
    if (!this.decoder || this.configured) return false
    const description = this.buildAvccDescription()
    if (!description) {
      console.log('[H264Decoder] configure skipped: no SPS+PPS yet')
      return false
    }
    const codec = this.spsCodecString()
    // Only use the SPS-derived codec string when profile_idc is a well-known
    // 8-bit profile (66=Baseline, 77=Main, 88=Extended, 100=High).
    // Some devices (e.g. Huawei Kirin) produce non-standard profile IDs like
    // 103 (avc1.6742C0) which Chromium's VideoDecoder silently accepts but
    // never outputs frames from.
    const KNOWN_8BIT_PROFILES = new Set([66, 77, 88, 100])
    const profileIdc = this.sps ? (this.stripStartCode(this.sps)[0] ?? 0) : 0
    const isKnownProfile = KNOWN_8BIT_PROFILES.has(profileIdc)
    if (!isKnownProfile && codec) {
      console.warn('[H264Decoder] unknown/non-standard profile detected (' + codec + ' profileIdc=' + profileIdc + '), skipping — using safe fallbacks')
    }
    // Build a priority list of codec strings to try.
    // Many Chromium/Electron builds only support Baseline/Main/High profiles,
    // so we fall back to the most widely supported strings.
    const candidates: string[] = []
    if (codec && isKnownProfile) candidates.push(codec)
    // High Profile (most scrcpy streams use this)
    if (codec !== 'avc1.64001F') candidates.push('avc1.64001F')
    if (codec !== 'avc1.640028') candidates.push('avc1.640028')
    // Main Profile
    candidates.push('avc1.4D401F')
    // Baseline Profile (most widely supported)
    candidates.push('avc1.42E01F')

    for (const c of candidates) {
      // When the real SPS profile doesn't match the codec string we're trying,
      // the description bytes will contradict the codec and cause silent failure.
      // Skip description in that case — the decoder can pick up SPS/PPS in-band
      // from the first keyframe (which is already prepended with SPS+PPS).
      const descModes: boolean[] = codec !== c || !isKnownProfile
        ? [false, description ? true : false]
        : description ? [true, false] : [false]
      for (const withDesc of descModes) {
        try {
          const config: Record<string, unknown> = { codec: c, optimizeForLatency: true }
          if (withDesc && description) config.description = description
          this.decoder.configure(config)
          this.configured = true
          console.log('[H264Decoder] configure OK: codec=' + c + ' withDesc=' + withDesc)
          return true
        } catch {
          // try next
        }
      }
    }
    console.warn('[H264Decoder] all codec candidates failed')
    return false
  }

  private spsCodecString(): string | null {
    if (!this.sps) return null
    const spsBody = this.stripStartCode(this.sps)
    if (spsBody.length < 4) return null
    const profileIdc = spsBody[0]
    const constraintFlags = spsBody[1]
    const levelIdc = spsBody[2]
    const hex = (n: number) => {
      const s = n.toString(16).toUpperCase()
      return s.length === 1 ? '0' + s : s
    }
    return `avc1.${hex(profileIdc)}${hex(constraintFlags)}${hex(levelIdc)}`
  }

  private recreateDecoder() {
    if (!H264CanvasDecoder.isSupported()) return
    this.configured = false
    this.decoder = this.makeDecoder()
    this.configureWithCurrentSpsPps()
    // Flush pending slices into the new decoder
    this.flushPending()
  }

  private buildAvccDescription(): Uint8Array | null {
    if (!this.sps || !this.pps) return null
    const spsBody = this.stripStartCode(this.sps)
    const ppsBody = this.stripStartCode(this.pps)
    if (spsBody.length < 4 || ppsBody.length < 1) return null

    const out = new Uint8Array(11 + spsBody.length + ppsBody.length)
    out[0] = 1
    out[1] = spsBody[0]
    out[2] = spsBody[1]
    out[3] = spsBody[2]
    out[4] = 0xFF
    out[5] = 0xE1
    out[6] = (spsBody.length >> 8) & 0xFF
    out[7] = spsBody.length & 0xFF
    out.set(spsBody, 8)
    let offset = 8 + spsBody.length
    out[offset++] = 1
    out[offset++] = (ppsBody.length >> 8) & 0xFF
    out[offset++] = ppsBody.length & 0xFF
    out.set(ppsBody, offset)
    return out
  }

  private stripStartCode(nal: Uint8Array): Uint8Array {
    if (nal.length >= 4 && nal[0] === 0 && nal[1] === 0 && nal[2] === 0 && nal[3] === 1) {
      return nal.subarray(4)
    }
    if (nal.length >= 3 && nal[0] === 0 && nal[1] === 0 && nal[2] === 1) {
      return nal.subarray(3)
    }
    return nal
  }

  /** Feed pending buffered slices into the decoder, clearing the buffer. */
  private flushPending() {
    const decoder = this.decoder
    if (!decoder || !this.configured) return
    for (const slice of this.pendingSlices) {
      try {
        decoder.decode(
          new EncodedVideoChunk({
            type: slice.isKey ? 'key' : 'delta',
            timestamp: slice.timestamp,
            data: slice.data,
          }),
        )
      } catch {
        // Drop individual decode errors during flush
      }
    }
    this.pendingSlices = []
  }

  feed(chunk: ArrayBuffer) {
    if (!this.decoder) {
      if (H264CanvasDecoder.isSupported()) {
        console.log('[H264Decoder] feed called but no decoder, calling start()')
        this.start()
      }
    }
    const decoder = this.decoder
    if (!decoder) return

    const nalUnits = this.extractNalUnits(new Uint8Array(chunk))
    let spsSeen = false
    let ppsSeen = false
    let keySeen = false
    let deltaSeen = 0
    for (const nalUnit of nalUnits) {
      const nalType = this.nalType(nalUnit)
      if (nalType === 7) {
        spsSeen = true
        this.sps = nalUnit
        if (this.pps && !this.configured) {
          this.configureWithCurrentSpsPps()
        }
        continue
      }
      if (nalType === 8) {
        ppsSeen = true
        this.pps = nalUnit
        if (this.sps && !this.configured) {
          this.configureWithCurrentSpsPps()
        }
        continue
      }
      if (nalType !== 1 && nalType !== 5) {
        continue
      }

      const isKey = nalType === 5
      if (isKey) { keySeen = true } else { deltaSeen++ }

      const data = isKey && this.sps && this.pps
        ? this.concatNalUnits([this.sps, this.pps, nalUnit])
        : nalUnit

      // If not yet configured, buffer the slice until we are
      if (!this.configured) {
        this.pendingSlices.push({ isKey, timestamp: this.timestamp, data })
        this.timestamp += this.frameIntervalUs
        continue
      }

      // Decoder queue pressure — drop non-key frames when queue builds
      // up. Allow up to 8 pending frames (was 4) to avoid premature
      // frame drops during GPU decode latency spikes.
      if (!isKey && (decoder.decodeQueueSize ?? 0) > 8) {
        continue
      }

      try {
        decoder.decode(
          new EncodedVideoChunk({
            type: isKey ? 'key' : 'delta',
            timestamp: this.timestamp,
            data,
          }),
        )
        this.timestamp += this.frameIntervalUs
      } catch (e) {
        console.warn('[H264Decoder] decode failed:', e)
        if (this.decoder && this.decoder.state !== 'closed') {
          try { this.decoder.close() } catch {}
          this.decoder = null
          this.configured = false
        }
      }
    }
    // Only log on state changes (sps/pps first seen) or keyframe, not every delta frame
    if (spsSeen || ppsSeen || (keySeen && this._keyFrameCount < 5)) {
      if (keySeen) this._keyFrameCount++
      console.log('[H264Decoder] feed: NALs extracted=' + nalUnits.length,
        'sps=' + spsSeen, 'pps=' + ppsSeen, 'key=' + keySeen, 'delta=' + deltaSeen,
        'configured=' + this.configured)
    }

    // Flush the remaining buffer tail
    if (this.buffer.length > 4 && this.configured && this.startsWithStartCode(this.buffer)) {
      const shortStart = this.buffer[2] === 0x01
      const nalType = shortStart ? this.buffer[3] & 0x1f : this.buffer[4] & 0x1f
      if (nalType === 1 || nalType === 5) {
        const isKey = nalType === 5
        const data = isKey && this.sps && this.pps
          ? this.concatNalUnits([this.sps, this.pps, this.buffer])
          : this.buffer.slice()
        try {
          decoder.decode(
            new EncodedVideoChunk({
              type: isKey ? 'key' : 'delta',
              timestamp: this.timestamp,
              data,
            }),
          )
          this.timestamp += this.frameIntervalUs
        } catch {
          // drop
        }
      }
      this.buffer = new Uint8Array(0)
    }
  }

  private startsWithStartCode(data: Bytes): boolean {
    if (data.length >= 4 && data[0] === 0 && data[1] === 0 && data[2] === 0 && data[3] === 1) return true
    if (data.length >= 3 && data[0] === 0 && data[1] === 0 && data[2] === 1) return true
    return false
  }

  close() {
    if (this.decoder && this.decoder.state !== 'closed') {
      this.decoder.close()
    }
    this.decoder = null
    this.configured = false
    this.buffer = new Uint8Array(0)
    this.sps = null
    this.pps = null
    this.pendingSlices = []
  }

  private extractNalUnits(chunk: Bytes): Bytes[] {
    // Fast append: only allocate when buffer is non-empty.
    if (this.buffer.length > 0) {
      this.buffer = this.concatRaw(this.buffer, chunk)
    } else {
      this.buffer = chunk.slice() // clone to avoid mutating input
    }

    const starts = this.findStartCodes(this.buffer)
    if (starts.length < 2) {
      return []
    }

    const units: Bytes[] = []
    for (let index = 0; index < starts.length - 1; index += 1) {
      units.push(this.buffer.slice(starts[index], starts[index + 1]))
    }
    this.buffer = this.buffer.slice(starts[starts.length - 1])
    return units
  }

  private findStartCodes(data: Bytes): number[] {
    const starts: number[] = []
    const len = data.length
    // Skip quickly: look for 0x00 first, then check neighbours.
    // This avoids 4 comparisons per byte when most bytes are non-zero.
    for (let index = 0; index < len - 3; ) {
      // Fast-scan: advance until we see a 0x00 byte
      while (index < len - 3 && data[index] !== 0) index++
      if (index >= len - 3) break

      if (data[index + 1] === 0 && data[index + 2] === 0 && data[index + 3] === 1) {
        starts.push(index)
        index += 4
      } else if (data[index + 1] === 0 && data[index + 2] === 1) {
        starts.push(index)
        index += 3
      } else {
        index++
      }
    }
    return starts
  }

  private nalType(nalUnit: Bytes): number {
    let offset = 3
    if (nalUnit[2] === 0) {
      offset = 4
    }
    return nalUnit[offset] & 0x1f
  }

  private concatNalUnits(units: Bytes[]): Bytes {
    return this.concatRaw(...units)
  }

  private concatRaw(...chunks: Bytes[]): Bytes {
    const length = chunks.reduce((sum, item) => sum + item.length, 0)
    const result = new Uint8Array(length)
    let offset = 0
    for (const chunk of chunks) {
      result.set(chunk, offset)
      offset += chunk.length
    }
    return result
  }
}

export function createH264Decoder(
  canvas: HTMLCanvasElement,
  onError: (message: string) => void,
  targetFps?: number,
): { decoder: H264DecoderLike; mode: DecoderMode } {
  if (H264CanvasDecoder.isSupported()) {
    const dec = new H264CanvasDecoder(canvas, onError, targetFps ?? 60)
    return { decoder: dec, mode: 'webcodecs' }
  }

  if (H264MseDecoder.isSupported()) {
    const dec = new H264MseDecoder(canvas, onError)
    return { decoder: dec, mode: 'mse' }
  }

  throw new Error('当前浏览器不支持 H.264 解码（需要 WebCodecs 或 MSE）')
}
