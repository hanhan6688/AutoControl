export interface H264DecoderLike {
  start(): void
  feed(chunk: ArrayBuffer): void
  close(): void
  setCanvas(canvas: HTMLCanvasElement): void
}

export type DecoderMode = 'webcodecs' | 'mse'

/**
 * MSE (Media Source Extensions) H.264 decoder — fallback for browsers
 * that lack WebCodecs VideoDecoder (e.g. Firefox).
 *
 * Renders H.264 Annex-B stream via a hidden <video> + MediaSource,
 * then paints each video frame onto the target canvas via drawImage().
 */

// ---------- Minimal MP4 muxer -------------------------------------------

class Mp4Muxer {
  private seqNum = 0
  private trackId = 1
  private timescale = 90000
  private baseMediaDecodeTime = 0
  private sps: Uint8Array | null = null
  private pps: Uint8Array | null = null
  private width = 0
  private height = 0

  setParameterSets(sps: Uint8Array, pps: Uint8Array): void {
    this.sps = sps
    this.pps = pps
    // Parse SPS for width/height (simplified — uses dimensions from profile/level)
    if (sps.length > 4) {
      this.width = 0
      this.height = 0
    }
  }

  buildInitSegment(): Uint8Array {
    if (!this.sps || !this.pps) throw new Error('SPS/PPS not set')
    const ftyp = this.ftypBox()
    const moov = this.moovBox()
    return this.merge(ftyp, moov)
  }

  buildMediaSegment(nalData: Uint8Array, isKeyframe: boolean): Uint8Array {
    this.seqNum++
    const moof = this.moofBox(nalData.length, isKeyframe)
    const mdat = this.mdatBox(nalData)
    return this.merge(moof, mdat)
  }

  // --- box builders ---

  private ftypBox(): Uint8Array {
    return this.rawBox('isom', new Uint8Array([
      0x69, 0x73, 0x6f, 0x6d, // isom
      0x00, 0x00, 0x02, 0x00, // minor version
      0x69, 0x73, 0x6f, 0x6d, // isom
      0x61, 0x76, 0x63, 0x31, // avc1
    ]))
  }

  private moovBox(): Uint8Array {
    const mvhd = this.mvhdBox()
    const trak = this.trakBox()
    return this.box('moov', mvhd, trak)
  }

  private mvhdBox(): Uint8Array {
    const data = new Uint8Array(108)
    const v = new DataView(data.buffer)
    v.setUint32(0, 108)
    this.writeType(data, 4, 'mvhd')
    v.setUint32(20, this.timescale)
    v.setUint32(96, 2) // next_track_ID
    return data
  }

  private trakBox(): Uint8Array {
    const tkhd = this.tkhdBox()
    const mdia = this.mdiaBox()
    return this.box('trak', tkhd, mdia)
  }

  private tkhdBox(): Uint8Array {
    const data = new Uint8Array(92)
    const v = new DataView(data.buffer)
    v.setUint32(0, 92)
    this.writeType(data, 4, 'tkhd')
    v.setUint32(8, 3) // flags: enabled | in_movie
    v.setUint32(20, this.trackId)
    // identity matrix
    v.setUint32(48, 0x10000)
    v.setUint32(60, 0x10000)
    v.setUint32(72, 0x40000000)
    return data
  }

  private mdiaBox(): Uint8Array {
    const mdhd = this.mdhdBox()
    const hdlr = this.hdlrBox()
    const minf = this.minfBox()
    return this.box('mdia', mdhd, hdlr, minf)
  }

  private mdhdBox(): Uint8Array {
    const data = new Uint8Array(32)
    const v = new DataView(data.buffer)
    v.setUint32(0, 32)
    this.writeType(data, 4, 'mdhd')
    v.setUint32(20, this.timescale)
    v.setUint16(28, 0x55c4) // und
    return data
  }

  private hdlrBox(): Uint8Array {
    const name = 'VideoHandler'
    const nameBytes = new TextEncoder().encode(name)
    // hdlr fullbox layout: 4B(size)+4B(type)+4B(ver/flags)+4B(pre_defined)+
    //   4B(handler_type)+12B(reserved)+name+1B(null)
    const data = new Uint8Array(8 + 24 + nameBytes.length + 1)
    const v = new DataView(data.buffer)
    v.setUint32(0, data.length)
    this.writeType(data, 4, 'hdlr')
    // pre_defined=0, handler_type='vide'
    data[16] = 0x76; data[17] = 0x69; data[18] = 0x64; data[19] = 0x65
    data.set(nameBytes, 32)
    return data
  }

  private minfBox(): Uint8Array {
    const vmhd = this.vmhdBox()
    const dinf = this.dinfBox()
    const stbl = this.stblBox()
    return this.box('minf', vmhd, dinf, stbl)
  }

  private vmhdBox(): Uint8Array {
    const data = new Uint8Array(16)
    const v = new DataView(data.buffer)
    v.setUint32(0, 16)
    this.writeType(data, 4, 'vmhd')
    v.setUint32(8, 1) // flags
    return data
  }

  private dinfBox(): Uint8Array {
    const dref = this.drefBox()
    return this.box('dinf', dref)
  }

  private drefBox(): Uint8Array {
    const urlBox = this.fullBox('url ', 1) // self-contained flag
    // dref fullbox: 4B(size)+4B(type)+4B(ver/flags)+4B(entry_count) + urlBox(12B) = 28B total
    const data = new Uint8Array(16 + urlBox.length)
    const v = new DataView(data.buffer)
    v.setUint32(0, data.length)
    this.writeType(data, 4, 'dref')
    v.setUint32(8, 0) // version + flags
    v.setUint32(12, 1) // entry_count
    data.set(urlBox, 16)
    return data
  }

  private stblBox(): Uint8Array {
    const stsd = this.stsdBox()
    const stts = this.fullBox('stts', 0)
    const stsc = this.fullBox('stsc', 0)
    const stsz = this.fullBox('stsz', 0)
    const stco = this.fullBox('stco', 0)
    return this.box('stbl', stsd, stts, stsc, stsz, stco)
  }

  private stsdBox(): Uint8Array {
    const avc1 = this.avc1Box()
    const data = new Uint8Array(16 + avc1.length)
    const v = new DataView(data.buffer)
    v.setUint32(0, data.length)
    this.writeType(data, 4, 'stsd')
    v.setUint32(12, 1) // entry_count
    data.set(avc1, 16)
    return data
  }

  private avc1Box(): Uint8Array {
    const avcC = this.avcCBox()
    const prefixSize = 78 // 6 reserved + 2 data_ref + ... + 32 compressor_name + 2 depth + 2 pre_defined
    const totalSize = 8 + prefixSize + avcC.length
    const data = new Uint8Array(totalSize)
    const v = new DataView(data.buffer)
    v.setUint32(0, totalSize)
    this.writeType(data, 4, 'avc1')
    v.setUint16(14, 1) // data_ref_idx
    v.setUint16(30, 0x0048) // horiz_res 72 dpi
    v.setUint16(34, 0x0048) // vert_res
    v.setUint16(50, 1) // frame_count
    // compressor_name: 32 bytes of zeros (offset 52-83)
    v.setUint16(82, 0x0018) // depth
    v.setInt16(84, -1) // pre_defined
    data.set(avcC, 8 + prefixSize)
    return data
  }

  private avcCBox(): Uint8Array {
    if (!this.sps || !this.pps) throw new Error('SPS/PPS not set')
    const spsData = this.sps
    const ppsData = this.pps
    const size = 15 + spsData.length + ppsData.length
    const data = new Uint8Array(8 + size)
    const v = new DataView(data.buffer)
    v.setUint32(0, data.length)
    this.writeType(data, 4, 'avcC')
    let off = 8
    data[off++] = 1 // configurationVersion
    data[off++] = spsData[1] // profile
    data[off++] = spsData[2] // compat
    data[off++] = spsData[3] // level
    data[off++] = 0xff // lengthSizeMinusOne = 3
    data[off++] = 0xe1 // numSPS = 1 (with reserved bits)
    v.setUint16(off, spsData.length)
    off += 2
    data.set(spsData, off)
    off += spsData.length
    data[off++] = 1 // numPPS
    v.setUint16(off, ppsData.length)
    off += 2
    data.set(ppsData, off)
    return data
  }

  private moofBox(sampleSize: number, isKeyframe: boolean): Uint8Array {
    const mfhd = this.mfhdBox()
    const traf = this.trafBox(sampleSize, isKeyframe)
    return this.box('moof', mfhd, traf)
  }

  private mfhdBox(): Uint8Array {
    const data = new Uint8Array(16)
    const v = new DataView(data.buffer)
    v.setUint32(0, 16)
    this.writeType(data, 4, 'mfhd')
    v.setUint32(12, this.seqNum)
    return data
  }

  private trafBox(sampleSize: number, isKeyframe: boolean): Uint8Array {
    const tfhd = this.tfhdBox()
    const tfdt = this.tfdtBox()
    const trun = this.trunBox(sampleSize, isKeyframe)
    return this.box('traf', tfhd, tfdt, trun)
  }

  private tfhdBox(): Uint8Array {
    const data = new Uint8Array(16)
    const v = new DataView(data.buffer)
    v.setUint32(0, 16)
    this.writeType(data, 4, 'tfhd')
    v.setUint32(8, 0x020000) // default-base-is-moof
    v.setUint32(12, this.trackId)
    return data
  }

  private tfdtBox(): Uint8Array {
    const data = new Uint8Array(20)
    const v = new DataView(data.buffer)
    v.setUint32(0, 20)
    this.writeType(data, 4, 'tfdt')
    v.setUint32(8, 1) // version 1
    v.setUint32(16, this.baseMediaDecodeTime)
    this.baseMediaDecodeTime++
    return data
  }

  private trunBox(sampleSize: number, isKeyframe: boolean): Uint8Array {
    // version=0, flags=0x000301 (sample-duration | sample-size | sample-flags)
    const data = new Uint8Array(28)
    const v = new DataView(data.buffer)
    v.setUint32(0, 28)
    this.writeType(data, 4, 'trun')
    v.setUint32(8, 0x000301) // flags
    v.setUint32(12, 1) // sample_count
    v.setUint32(16, 1) // sample_duration (1 timescale tick)
    v.setUint32(20, sampleSize) // sample_size
    // sample_flags: non-sync = 0x01000000, sync = 0x02000000
    // Actually: depends_on=2 for I-frame (0x02000000), depends_on=1 for non-I (0x01000000)
    v.setUint32(24, isKeyframe ? 0x02000000 : 0x01000000)
    return data
  }

  private mdatBox(payload: Uint8Array): Uint8Array {
    const totalSize = 8 + payload.length
    const data = new Uint8Array(totalSize)
    const v = new DataView(data.buffer)
    v.setUint32(0, totalSize)
    this.writeType(data, 4, 'mdat')
    data.set(payload, 8)
    return data
  }

  // --- helpers ---

  private box(type: string, ...children: Uint8Array[]): Uint8Array {
    const contentLen = children.reduce((s, c) => s + c.length, 0)
    const data = new Uint8Array(8 + contentLen)
    const v = new DataView(data.buffer)
    v.setUint32(0, data.length)
    this.writeType(data, 4, type)
    let off = 8
    for (const child of children) {
      data.set(child, off)
      off += child.length
    }
    return data
  }

  private rawBox(type: string, content: Uint8Array): Uint8Array {
    const data = new Uint8Array(8 + content.length)
    const v = new DataView(data.buffer)
    v.setUint32(0, data.length)
    this.writeType(data, 4, type)
    data.set(content, 8)
    return data
  }

  private fullBox(type: string, flags: number): Uint8Array {
    const data = new Uint8Array(12)
    const v = new DataView(data.buffer)
    v.setUint32(0, 12)
    this.writeType(data, 4, type)
    v.setUint32(8, flags)
    return data
  }

  private writeType(buf: Uint8Array, offset: number, type: string): void {
    for (let i = 0; i < 4; i++) buf[offset + i] = type.charCodeAt(i)
  }

  private merge(...chunks: Uint8Array[]): Uint8Array {
    const total = chunks.reduce((s, c) => s + c.length, 0)
    const result = new Uint8Array(total)
    let off = 0
    for (const c of chunks) {
      result.set(c, off)
      off += c.length
    }
    return result
  }
}

// ---------- MSE Decoder -------------------------------------------------

export class H264MseDecoder implements H264DecoderLike {
  private mediaSource: MediaSource | null = null
  private sourceBuffer: SourceBuffer | null = null
  private videoEl: HTMLVideoElement | null = null
  private context: CanvasRenderingContext2D
  private rafId: number | null = null
  private muxer = new Mp4Muxer()
  private initialized = false
  private pendingAppends: Uint8Array[] = []
  private bufferBusy = false
  private bufferQueue: Uint8Array = new Uint8Array(0)
  private sps: Uint8Array | null = null
  private pps: Uint8Array | null = null

  constructor(
    private canvas: HTMLCanvasElement,
    private readonly onError: (message: string) => void,
  ) {
    const context = canvas.getContext('2d')
    if (!context) throw new Error('Canvas 2D context is not available')
    this.context = context
  }

  static isSupported(): boolean {
    if (typeof MediaSource === 'undefined') return false
    return MediaSource.isTypeSupported('video/mp4; codecs="avc1.42E01F"')
      || MediaSource.isTypeSupported('video/mp4; codecs="avc1.42C01E"')
  }

  setCanvas(canvas: HTMLCanvasElement): void {
    this.canvas = canvas
    const ctx = canvas.getContext('2d')
    if (ctx) this.context = ctx
  }

  start(): void {
    if (!H264MseDecoder.isSupported()) {
      throw new Error('当前浏览器不支持 MSE H.264 解码')
    }

    this.videoEl = document.createElement('video')
    this.videoEl.muted = true
    this.videoEl.playsInline = true
    this.videoEl.style.display = 'none'
    document.body.appendChild(this.videoEl)

    this.mediaSource = new MediaSource()
    const blobUrl = URL.createObjectURL(this.mediaSource)
    this.videoEl.src = blobUrl

    const onSourceOpen = () => {
      try {
        const codec = MediaSource.isTypeSupported('video/mp4; codecs="avc1.42E01F"')
          ? 'video/mp4; codecs="avc1.42E01F"'
          : 'video/mp4; codecs="avc1.42C01E"'
        this.sourceBuffer = this.mediaSource!.addSourceBuffer(codec)
        this.sourceBuffer.mode = 'segments'
        this.sourceBuffer.addEventListener('updateend', () => {
          this.bufferBusy = false
          this.drainPending()
        })
        this.sourceBuffer.addEventListener('error', () => {
          this.bufferBusy = false
          this.drainPending()
        })
      } catch (exc) {
        this.onError(`MSE addSourceBuffer failed: ${exc}`)
      }
    }
    this.mediaSource.addEventListener('sourceopen', onSourceOpen)
    // Store reference so close() can remove the listener and revoke the correct URL
    ;(this.mediaSource as any).__onSourceOpen = onSourceOpen
    ;(this.mediaSource as any).__blobUrl = blobUrl

    this.startRenderLoop()
  }

  feed(chunk: ArrayBuffer): void {
    const data = new Uint8Array(chunk)
    const nalUnits = this.splitNalUnits(data)

    for (const nal of nalUnits) {
      const nalType = this.nalType(nal)

      if (nalType === 7) {
        // SPS
        this.sps = this.stripStartCode(nal)
        continue
      }
      if (nalType === 8) {
        // PPS
        this.pps = this.stripStartCode(nal)
        continue
      }

      // Only process IDR (5) and non-IDR (1) slices
      if (nalType !== 1 && nalType !== 5) continue

      const isKeyframe = nalType === 5

      if (!this.initialized) {
        if (isKeyframe && this.sps && this.pps) {
          this.muxer.setParameterSets(this.sps, this.pps)
          const initSegment = this.muxer.buildInitSegment()
          this.appendData(initSegment)
          this.initialized = true
        } else {
          continue
        }
      }

      // Convert Annex-B to AVCC (length-prefixed)
      const nalPayload = this.stripStartCode(nal)
      const avccNal = this.toAvcc(nalPayload)

      if (isKeyframe && this.sps && this.pps) {
        // Re-send init segment on new keyframe (some browsers need this)
        this.muxer = new Mp4Muxer()
        this.muxer.setParameterSets(this.sps, this.pps)
        const initSeg = this.muxer.buildInitSegment()
        this.appendData(initSeg)
      }

      const mediaSegment = this.muxer.buildMediaSegment(avccNal, isKeyframe)
      this.appendData(mediaSegment)

      // Auto-play on first frame
      if (this.videoEl && this.videoEl.paused && this.videoEl.readyState >= 2) {
        this.videoEl.play().catch(() => {})
      }
    }
  }

  close(): void {
    if (this.rafId !== null) {
      cancelAnimationFrame(this.rafId)
      this.rafId = null
    }
    try {
      if (this.sourceBuffer && this.mediaSource?.readyState === 'open') {
        this.mediaSource.removeSourceBuffer(this.sourceBuffer)
      }
    } catch { /* ignore */ }
    this.sourceBuffer = null
    try {
      if (this.mediaSource?.readyState === 'open') {
        this.mediaSource.endOfStream()
      }
    } catch { /* ignore */ }
    if (this.videoEl) {
      const blobUrl = (this.mediaSource as any)?.__blobUrl ?? this.videoEl.src
      this.videoEl.pause()
      this.videoEl.removeAttribute('src')
      this.videoEl.load()
      URL.revokeObjectURL(blobUrl)
      this.videoEl.remove()
    }
    this.videoEl = null
    if (this.mediaSource) {
      const onSourceOpen = (this.mediaSource as any).__onSourceOpen
      if (onSourceOpen) {
        this.mediaSource.removeEventListener('sourceopen', onSourceOpen)
      }
      this.mediaSource = null
    }
    this.initialized = false
    this.pendingAppends = []
    this.bufferBusy = false
    this.sps = null
    this.pps = null
  }

  // --- Private ---

  private startRenderLoop(): void {
    const render = () => {
      if (!this.videoEl) return
      if (this.videoEl.readyState >= 2 && this.videoEl.videoWidth > 0) {
        const vw = this.videoEl.videoWidth
        const vh = this.videoEl.videoHeight
        if (this.canvas.width !== vw || this.canvas.height !== vh) {
          this.canvas.width = vw
          this.canvas.height = vh
        }
        this.context.drawImage(this.videoEl, 0, 0)
      }
      this.rafId = requestAnimationFrame(render)
    }
    this.rafId = requestAnimationFrame(render)
  }

  private appendData(data: Uint8Array): void {
    this.pendingAppends.push(data)
    this.drainPending()
  }

  private drainPending(): void {
    if (!this.sourceBuffer || this.bufferBusy || this.pendingAppends.length === 0) return
    if (this.mediaSource?.readyState !== 'open') return

    const total = this.pendingAppends.reduce((s, c) => s + c.length, 0)
    const merged = new Uint8Array(total)
    let off = 0
    for (const chunk of this.pendingAppends) {
      merged.set(chunk, off)
      off += chunk.length
    }
    this.pendingAppends = []
    this.bufferBusy = true

    try {
      this.sourceBuffer.appendBuffer(merged)
    } catch (exc) {
      this.bufferBusy = false
      this.onError(`MSE appendBuffer error: ${exc}`)
    }
  }

  // --- NAL parsing ---

  private buffer: Uint8Array = new Uint8Array(0)

  private splitNalUnits(chunk: Uint8Array): Uint8Array[] {
    this.buffer = this.concat(this.buffer, chunk)
    const starts = this.findStartCodes(this.buffer)
    if (starts.length < 2) return []

    const units: Uint8Array[] = []
    for (let i = 0; i < starts.length - 1; i++) {
      units.push(this.buffer.slice(starts[i], starts[i + 1]))
    }
    this.buffer = this.buffer.slice(starts[starts.length - 1])
    return units
  }

  private findStartCodes(data: Uint8Array): number[] {
    const starts: number[] = []
    for (let i = 0; i < data.length - 3; i++) {
      if (data[i] === 0 && data[i + 1] === 0 && data[i + 2] === 0 && data[i + 3] === 1) {
        starts.push(i)
        i += 3
      } else if (data[i] === 0 && data[i + 1] === 0 && data[i + 2] === 1) {
        starts.push(i)
        i += 2
      }
    }
    return starts
  }

  private nalType(nal: Uint8Array): number {
    const offset = (nal[2] === 1) ? 3 : 4
    return nal[offset] & 0x1f
  }

  private stripStartCode(nal: Uint8Array): Uint8Array {
    if (nal[0] === 0 && nal[1] === 0 && nal[2] === 0 && nal[3] === 1) return nal.slice(4)
    if (nal[0] === 0 && nal[1] === 0 && nal[2] === 1) return nal.slice(3)
    return nal
  }

  private toAvcc(nalPayload: Uint8Array): Uint8Array {
    const len = nalPayload.length
    const avcc = new Uint8Array(4 + len)
    avcc[0] = (len >>> 24) & 0xff
    avcc[1] = (len >>> 16) & 0xff
    avcc[2] = (len >>> 8) & 0xff
    avcc[3] = len & 0xff
    avcc.set(nalPayload, 4)
    return avcc
  }

  private concat(...chunks: Uint8Array[]): Uint8Array {
    const len = chunks.reduce((s, c) => s + c.length, 0)
    const result = new Uint8Array(len)
    let off = 0
    for (const c of chunks) {
      result.set(c, off)
      off += c.length
    }
    return result
  }
}