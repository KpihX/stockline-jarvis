/**
 * Pure-TypeScript WebRTC Opus (48 kHz) <-> WhatsApp VoIP PCM (16 kHz) bridge.
 *
 * Responsibilities:
 *  - Negotiate an RTCPeerConnection with the admin's browser (Opus 48 kHz, DTLS-SRTP)
 *  - Upsample 16 kHz caller PCM -> 48 kHz Opus RTP packets toward the browser
 *  - Decode 48 kHz browser mic Opus RTP -> 16 kHz Float32 PCM chunks in a bounded 200 ms queue
 *  - Tap clean 16 kHz caller PCM through an RMS energy VAD to emit WAV utterances for Whisper STT
 */

import { randomInt } from 'node:crypto'
import OpusScript from 'opusscript'
import {
  MediaStreamTrack,
  RTCPeerConnection,
  RTCRtpCodecParameters,
  RtpHeader,
  RtpPacket,
} from 'werift'

export interface BridgeConfig {
  sampleRate: number
  webrtcRate: number
  channels: number
  framesPerChunk: number
  vadRmsThreshold: number
  vadSilenceMs: number
  vadMaxUtteranceMs: number
  icePortMin: number
  icePortMax: number
  iceServers: string[]
}

export type UtteranceHandler = (wavBuffer: Buffer, durationMs: number) => void

export function encodeWav16kMono(samples: Int16Array, sampleRate = 16000): Buffer {
  const dataBytes = samples.length * 2
  const buf = Buffer.allocUnsafe(44 + dataBytes)
  buf.write('RIFF', 0)
  buf.writeUInt32LE(36 + dataBytes, 4)
  buf.write('WAVE', 8)
  buf.write('fmt ', 12)
  buf.writeUInt32LE(16, 16) // PCM fmt chunk size
  buf.writeUInt16LE(1, 20) // PCM format
  buf.writeUInt16LE(1, 22) // mono
  buf.writeUInt32LE(sampleRate, 24)
  buf.writeUInt32LE(sampleRate * 2, 28) // byte rate
  buf.writeUInt16LE(2, 32) // block align
  buf.writeUInt16LE(16, 34) // bits per sample
  buf.write('data', 36)
  buf.writeUInt32LE(dataBytes, 40)
  Buffer.from(samples.buffer, samples.byteOffset, dataBytes).copy(buf, 44)
  return buf
}

export function decodeWav16kMono(wav: Buffer): Float32Array {
  if (wav.length < 44 || wav.toString('ascii', 0, 4) !== 'RIFF') {
    throw new Error('Invalid WAV header')
  }
  let offset = 12
  let audioRate = 16000
  let channels = 1
  let bitsPerSample = 16
  let dataOffset = -1
  let dataLength = 0

  while (offset + 8 <= wav.length) {
    const id = wav.toString('ascii', offset, offset + 4)
    const size = wav.readUInt32LE(offset + 4)
    const body = offset + 8
    if (id === 'fmt ' && body + 16 <= wav.length) {
      channels = wav.readUInt16LE(body + 2)
      audioRate = wav.readUInt32LE(body + 4)
      bitsPerSample = wav.readUInt16LE(body + 14)
    } else if (id === 'data') {
      dataOffset = body
      dataLength = Math.min(size, wav.length - body)
      break
    }
    offset = body + size + (size % 2)
  }

  if (dataOffset < 0 || dataLength <= 0) {
    return new Float32Array(0)
  }
  if (bitsPerSample !== 16) {
    throw new Error(`Unsupported WAV bit depth: ${bitsPerSample}`)
  }

  const frameCount = Math.floor(dataLength / (2 * Math.max(1, channels)))
  const mono = new Float32Array(frameCount)
  for (let i = 0; i < frameCount; i++) {
    let sum = 0
    for (let ch = 0; ch < channels; ch++) {
      const sampleOffset = dataOffset + (i * channels + ch) * 2
      sum += wav.readInt16LE(sampleOffset) / 32768
    }
    mono[i] = sum / channels
  }

  if (audioRate === 16000) return mono
  const targetLen = Math.max(1, Math.round((mono.length * 16000) / audioRate))
  const resampled = new Float32Array(targetLen)
  const ratio = mono.length / targetLen
  for (let i = 0; i < targetLen; i++) {
    const src = i * ratio
    const idx = Math.floor(src)
    const frac = src - idx
    const a = mono[Math.min(idx, mono.length - 1)]
    const b = mono[Math.min(idx + 1, mono.length - 1)]
    resampled[i] = a + (b - a) * frac
  }
  return resampled
}

class VadUtteranceSegmenter {
  private readonly sampleRate: number
  private readonly rmsThreshold: number
  private readonly silenceSamplesTarget: number
  private readonly maxUtteranceSamples: number
  private readonly preRollMaxChunks = 10
  private readonly preRoll: Int16Array[] = []
  private readonly onUtterance: UtteranceHandler

  private activeChunks: Int16Array[] = []
  private activeSamples = 0
  private silenceSamples = 0
  private speaking = false

  constructor(
    sampleRate: number,
    rmsThreshold: number,
    silenceMs: number,
    maxUtteranceMs: number,
    onUtterance: UtteranceHandler
  ) {
    this.sampleRate = sampleRate
    this.rmsThreshold = rmsThreshold
    this.silenceSamplesTarget = Math.max(sampleRate * 0.4, Math.round((sampleRate * silenceMs) / 1000))
    this.maxUtteranceSamples = Math.max(sampleRate * 2, Math.round((sampleRate * maxUtteranceMs) / 1000))
    this.onUtterance = onUtterance
  }

  push(pcm16k: Float32Array): void {
    if (pcm16k.length === 0) return
    let energy = 0
    const int16 = new Int16Array(pcm16k.length)
    for (let i = 0; i < pcm16k.length; i++) {
      const clamped = Math.max(-1, Math.min(1, pcm16k[i]))
      energy += clamped * clamped
      int16[i] = Math.round(clamped * 32767)
    }
    const rms = Math.sqrt(energy / pcm16k.length)

    if (!this.speaking) {
      this.preRoll.push(int16)
      if (this.preRoll.length > this.preRollMaxChunks) {
        this.preRoll.shift()
      }
      if (rms >= this.rmsThreshold) {
        this.speaking = true
        this.silenceSamples = 0
        this.activeChunks = [...this.preRoll]
        this.activeSamples = this.activeChunks.reduce((acc, item) => acc + item.length, 0)
        this.preRoll.length = 0
      }
      return
    }

    this.activeChunks.push(int16)
    this.activeSamples += int16.length
    if (rms >= this.rmsThreshold) {
      this.silenceSamples = 0
    } else {
      this.silenceSamples += int16.length
    }

    if (this.silenceSamples >= this.silenceSamplesTarget || this.activeSamples >= this.maxUtteranceSamples) {
      this.emitBuffered()
    }
  }

  flush(): void {
    if (this.speaking && this.activeSamples >= Math.round(this.sampleRate * 0.35)) {
      this.emitBuffered()
    } else {
      this.reset()
    }
  }

  private emitBuffered(): void {
    const merged = new Int16Array(this.activeSamples)
    let offset = 0
    for (const chunk of this.activeChunks) {
      merged.set(chunk, offset)
      offset += chunk.length
    }
    const durationMs = Math.round((this.activeSamples / this.sampleRate) * 1000)
    this.reset()
    if (durationMs >= 350) {
      this.onUtterance(encodeWav16kMono(merged, this.sampleRate), durationMs)
    }
  }

  private reset(): void {
    this.speaking = false
    this.activeChunks = []
    this.activeSamples = 0
    this.silenceSamples = 0
  }
}

export class WebRtcCallBridge {
  readonly callId: string
  private readonly cfg: BridgeConfig
  private readonly encoder: OpusScript
  private readonly decoder: OpusScript
  private readonly vad: VadUtteranceSegmenter
  private readonly managerVad: VadUtteranceSegmenter | null
  private readonly outboundQueue: Float32Array[] = []
  private readonly maxOutboundChunks = 10 // ~200 ms at 20 ms/chunk
  private readonly ssrc = randomInt(100_000, 0x7fffffff)

  private pc: RTCPeerConnection | null = null
  private audioTrack: MediaStreamTrack | null = null
  private negotiatedPayloadType = 111
  private rtpSeq = randomInt(1, 30_000)
  private rtpTimestamp = randomInt(1, 0x0fffffff)
  private lastSample16k = 0
  private pending16k: number[] = []
  private pending48kDown: number[] = []
  private muted = false
  private closed = false

  stats = {
    inboundChunks16k: 0,
    outboundRtpSent: 0,
    inboundBrowserRtp: 0,
    outboundWaChunks: 0,
    droppedMicChunks: 0,
    connectionState: 'new',
  }

  constructor(
    callId: string,
    cfg: BridgeConfig,
    onUtterance: UtteranceHandler,
    onManagerUtterance?: UtteranceHandler
  ) {
    this.callId = callId
    this.cfg = cfg
    this.encoder = new OpusScript(48000, 1, OpusScript.Application.VOIP)
    this.decoder = new OpusScript(48000, 1, OpusScript.Application.VOIP)
    this.vad = new VadUtteranceSegmenter(
      cfg.sampleRate,
      cfg.vadRmsThreshold,
      cfg.vadSilenceMs,
      cfg.vadMaxUtteranceMs,
      onUtterance
    )
    this.managerVad = onManagerUtterance
      ? new VadUtteranceSegmenter(
          cfg.sampleRate,
          cfg.vadRmsThreshold,
          cfg.vadSilenceMs,
          cfg.vadMaxUtteranceMs,
          onManagerUtterance
        )
      : null
  }

  setMuted(muted: boolean): void {
    this.muted = muted
  }

  isMuted(): boolean {
    return this.muted
  }

  async acceptOffer(sdpOffer: string): Promise<string> {
    if (this.closed) throw new Error('Bridge already closed')
    if (this.pc) {
      await this.closePeerOnly()
    }

    const opusCodec = new RTCRtpCodecParameters({
      mimeType: 'audio/opus',
      clockRate: 48000,
      channels: 2,
      payloadType: 111,
      parameters: 'minptime=10;useinbandfec=1',
    })

    const iceServers = this.cfg.iceServers
      .map((url) => url.trim())
      .filter(Boolean)
      .map((urls) => ({ urls }))

    const pc = new RTCPeerConnection({
      codecs: { audio: [opusCodec] },
      iceServers: iceServers.length ? iceServers : [{ urls: 'stun:stun.l.google.com:19302' }],
      icePortRange: [this.cfg.icePortMin, this.cfg.icePortMax],
    })
    this.pc = pc

    const track = new MediaStreamTrack({ kind: 'audio' })
    this.audioTrack = track
    pc.addTransceiver(track, { direction: 'sendrecv' })

    pc.connectionStateChange.subscribe((state) => {
      this.stats.connectionState = state
      console.log(`[webrtc:${this.callId}] connectionState=${state}`)
    })

    pc.ontrack = (ev) => {
      if (ev.track.kind !== 'audio') return
      ev.track.onReceiveRtp.subscribe((rtp) => {
        if (this.closed) return
        this.handleBrowserRtp(rtp)
      })
    }

    await pc.setRemoteDescription({ type: 'offer', sdp: sdpOffer })
    const answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    await new Promise<void>((resolve) => {
      if (pc.iceGatheringState === 'complete') {
        resolve()
        return
      }
      const timer = setTimeout(resolve, 2500)
      pc.iceGatheringStateChange.subscribe((state) => {
        if (state === 'complete') {
          clearTimeout(timer)
          resolve()
        }
      })
    })

    const localSdp = pc.localDescription?.sdp || answer.sdp
    const opusMatch = localSdp.match(/a=rtpmap:(\d+)\s+opus\/48000/i)
    if (opusMatch) {
      this.negotiatedPayloadType = Number(opusMatch[1])
    }
    return localSdp
  }

  /** Receive 16 kHz mono Float32 PCM from caller (WhatsApp or simulator). */
  pushCallerPcm16k(pcm16k: Float32Array): void {
    if (this.closed || pcm16k.length === 0) return
    this.stats.inboundChunks16k += 1

    // 1. Feed AI VAD segmenter cleanly at native 16 kHz.
    this.vad.push(pcm16k)

    // 2. Buffer and upsample 16 kHz -> 48 kHz Opus 20ms frames (320 @ 16k -> 960 @ 48k)
    if (!this.audioTrack || this.stats.connectionState !== 'connected') {
      // Still track last sample so transition to connected has zero discontinuity.
      this.lastSample16k = pcm16k[pcm16k.length - 1]
      return
    }

    for (let i = 0; i < pcm16k.length; i++) {
      this.pending16k.push(pcm16k[i])
    }

    const frame16k = this.cfg.framesPerChunk // 320
    while (this.pending16k.length >= frame16k) {
      const slice = this.pending16k.splice(0, frame16k)
      const pcm48k = new Int16Array(frame16k * 3) // 960 samples = 20 ms @ 48 kHz
      let prev = this.lastSample16k
      for (let i = 0; i < frame16k; i++) {
        const cur = Math.max(-1, Math.min(1, slice[i]))
        const s0 = prev + (cur - prev) * (1 / 3)
        const s1 = prev + (cur - prev) * (2 / 3)
        const s2 = cur
        const base = i * 3
        pcm48k[base] = Math.round(s0 * 32767)
        pcm48k[base + 1] = Math.round(s1 * 32767)
        pcm48k[base + 2] = Math.round(s2 * 32767)
        prev = cur
      }
      this.lastSample16k = prev

      try {
        const opusPayload = this.encoder.encode(
          Buffer.from(pcm48k.buffer, pcm48k.byteOffset, pcm48k.byteLength),
          960
        )
        const seq = this.rtpSeq & 0xffff
        const ts = this.rtpTimestamp >>> 0
        this.rtpSeq += 1
        this.rtpTimestamp += 960
        const pkt = new RtpPacket(
          new RtpHeader({
            payloadType: this.negotiatedPayloadType,
            sequenceNumber: seq,
            timestamp: ts,
            ssrc: this.ssrc,
            marker: this.stats.outboundRtpSent === 0,
          }),
          opusPayload
        )
        this.audioTrack.writeRtp(pkt)
        this.stats.outboundRtpSent += 1
      } catch (err) {
        console.error(`[webrtc:${this.callId}] opus encode/writeRtp failed`, err)
      }
    }
  }

  /** Drain one 20ms Float32Array(320) chunk from browser mic toward WhatsApp caller. */
  drainOutboundChunk(frames = this.cfg.framesPerChunk): Float32Array {
    this.stats.outboundWaChunks += 1
    if (this.muted || this.outboundQueue.length === 0) {
      return new Float32Array(frames)
    }
    const next = this.outboundQueue.shift()!
    if (next.length === frames) return next
    const resized = new Float32Array(frames)
    resized.set(next.subarray(0, frames))
    return resized
  }

  flushVad(): void {
    this.vad.flush()
    this.managerVad?.flush()
  }

  async close(): Promise<void> {
    if (this.closed) return
    this.closed = true
    this.vad.flush()
    this.managerVad?.flush()
    await this.closePeerOnly()
    this.outboundQueue.length = 0
    try {
      this.encoder.delete()
    } catch {}
    try {
      this.decoder.delete()
    } catch {}
  }

  private async closePeerOnly(): Promise<void> {
    try {
      this.audioTrack?.stop()
    } catch {}
    this.audioTrack = null
    if (this.pc) {
      try {
        await this.pc.close()
      } catch {}
      this.pc = null
    }
  }

  private handleBrowserRtp(rtp: RtpPacket): void {
    if (!rtp.payload || rtp.payload.length === 0) return
    this.stats.inboundBrowserRtp += 1
    try {
      const decodedBuf = this.decoder.decode(rtp.payload)
      const pcm48 = new Int16Array(
        decodedBuf.buffer,
        decodedBuf.byteOffset,
        Math.floor(decodedBuf.byteLength / 2)
      )
      for (let i = 0; i < pcm48.length; i++) {
        this.pending48kDown.push(pcm48[i] / 32768)
      }

      const needed48 = this.cfg.framesPerChunk * 3 // 960 samples -> 320 @ 16k
      while (this.pending48kDown.length >= needed48) {
        const block = this.pending48kDown.splice(0, needed48)
        const out16 = new Float32Array(this.cfg.framesPerChunk)
        for (let i = 0; i < this.cfg.framesPerChunk; i++) {
          const b = i * 3
          out16[i] = (block[b] + block[b + 1] + block[b + 2]) / 3
        }
        if (!this.muted && this.managerVad) {
          this.managerVad.push(out16)
        }
        if (this.outboundQueue.length >= this.maxOutboundChunks) {
          this.outboundQueue.shift()
          this.stats.droppedMicChunks += 1
        }
        this.outboundQueue.push(out16)
      }
    } catch {
      // Ignore comfort noise / DTX / transient decode hiccups
    }
  }
}
