/**
 * WhatsApp VoIP manager using @innovatorssoft/baileys + WebRtcCallBridge.
 *
 * Bridges real incoming WhatsApp calls (VoipClient.on('call_incoming')) AND
 * deterministic simulated incoming calls through the exact same WebRTC Opus +
 * VAD-to-Whisper pipeline.
 */

import { randomUUID } from 'node:crypto'
import { type BridgeConfig, WebRtcCallBridge, decodeWav16kMono } from './webrtc-bridge.js'

export interface ManagedCallInfo {
  call_id: string
  from: string
  mode: 'baileys_voip' | 'simulation'
  status: string
  is_video: boolean
  is_waiting: boolean
  started_at: string
  muted: boolean
  stats: WebRtcCallBridge['stats']
}

interface ManagedCall {
  callId: string
  from: string
  mode: 'baileys_voip' | 'simulation'
  status: string
  isVideo: boolean
  isWaiting: boolean
  startedAt: string
  session: any | null
  bridge: WebRtcCallBridge
  simSamples16k?: Float32Array
  simTimer?: NodeJS.Timeout | null
  pacingTimer?: NodeJS.Timeout | null
}

export type PhoneResolver = (jid: string) => string

export class VoipBridgeManager {
  private readonly apiUrl: string
  private readonly cfg: BridgeConfig
  private readonly maxConcurrentCalls: number
  private readonly pthreadPoolSize: number
  private readonly resolvePhone: PhoneResolver
  private readonly calls = new Map<string, ManagedCall>()

  private voip: any = null
  private attachedSock: any = null
  private incomingHandler: ((session: any) => void) | null = null

  constructor(opts: {
    apiUrl: string
    bridgeConfig: BridgeConfig
    maxConcurrentCalls: number
    pthreadPoolSize: number
    resolvePhone: PhoneResolver
  }) {
    this.apiUrl = opts.apiUrl
    this.cfg = opts.bridgeConfig
    this.maxConcurrentCalls = opts.maxConcurrentCalls
    this.pthreadPoolSize = opts.pthreadPoolSize
    this.resolvePhone = opts.resolvePhone
  }

  async attachSocket(sock: any): Promise<void> {
    if (!sock || this.attachedSock === sock) return
    this.attachedSock = sock
    try {
      if (this.voip && this.incomingHandler) {
        try {
          this.voip.off?.('call_incoming', this.incomingHandler) ??
            this.voip.removeListener?.('call_incoming', this.incomingHandler)
        } catch {}
      }

      if (typeof sock.getVoipClient === 'function') {
        this.voip = await sock.getVoipClient()
        this.voip.setOptions?.({
          maxConcurrentCalls: this.maxConcurrentCalls,
          pthreadPoolSize: this.pthreadPoolSize,
        })
        console.log('[voip] attached to built-in sock.getVoipClient()')
      } else {
        const mod: any = await import('@innovatorssoft/baileys')
        const VoipClient = mod.VoipClient || mod.default?.VoipClient
        if (!VoipClient) {
          console.warn('[voip] VoipClient export not found in @innovatorssoft/baileys')
          return
        }
        this.voip = new VoipClient({
          maxConcurrentCalls: this.maxConcurrentCalls,
          pthreadPoolSize: this.pthreadPoolSize,
          diagnostic: false,
        })
        await this.voip.initWithSocket(sock)
        console.log('[voip] VoipClient attached via initWithSocket(sock)')
      }

      this.incomingHandler = (session: any) => {
        void this.handleIncomingWhatsAppCall(session)
      }
      this.voip.on('call_incoming', this.incomingHandler)
    } catch (err) {
      console.error('[voip] failed to initialize VoipClient', err)
    }
  }

  listCalls(): ManagedCallInfo[] {
    return Array.from(this.calls.values()).map((c) => ({
      call_id: c.callId,
      from: c.from,
      mode: c.mode,
      status: c.status,
      is_video: c.isVideo,
      is_waiting: c.isWaiting,
      started_at: c.startedAt,
      muted: c.bridge.isMuted(),
      stats: { ...c.bridge.stats },
    }))
  }

  async acceptCall(callId: string, sdpOffer: string): Promise<{ call_id: string; status: string; sdp_answer: string; mode: string }> {
    const entry = this.calls.get(callId)
    const withTimeout = async <T>(p: Promise<T>, ms: number, label: string): Promise<T> => {
      let timer: NodeJS.Timeout | null = null
      try {
        return await Promise.race([
          p,
          new Promise<never>((_, reject) => {
            timer = setTimeout(() => reject(new Error(`${label} timed out after ${ms}ms`)), ms)
          }),
        ])
      } finally {
        if (timer) clearTimeout(timer)
      }
    }

    try {
      if (!entry) {
        throw new Error(`Call not found: ${callId}`)
      }
      const sdpAnswer = await withTimeout(entry.bridge.acceptOffer(sdpOffer), 10_000, 'WebRTC acceptOffer')
      entry.status = 'active'

      if (entry.mode === 'baileys_voip' && entry.session && this.voip) {
        await withTimeout(
          this.voip.acceptCall(callId, {
            audioSource: 'silence',
            isMicEnabled: true,
            isCameraEnabled: false,
          }),
          12_000,
          'WhatsApp acceptCall'
        )
      } else if (entry.mode === 'simulation' && entry.simSamples16k && entry.simSamples16k.length > 0) {
        this.startSimPlayback(entry, entry.simSamples16k)
      }

      void this.postCallWebhook({
        event: 'call.state',
        call_id: callId,
        from: entry.from,
        status: 'active',
        mode: entry.mode,
      })

      return {
        call_id: callId,
        status: 'active',
        sdp_answer: sdpAnswer,
        mode: entry.mode,
      }
    } catch (err) {
      void this.postCallWebhook({
        event: 'call.error',
        call_id: callId,
        from: entry?.from || '',
        error: err instanceof Error ? err.message : String(err),
      })
      throw err
    }
  }

  async rejectCall(callId: string, reason = 'declined'): Promise<{ call_id: string; status: string }> {
    const entry = this.calls.get(callId)
    if (entry?.mode === 'baileys_voip' && this.voip) {
      try {
        await this.voip.rejectCall(callId, reason)
      } catch (err) {
        console.warn('[voip] rejectCall failed', err)
      }
    }
    await this.cleanupCall(callId, 'rejected', reason)
    return { call_id: callId, status: 'rejected' }
  }

  async hangupCall(callId: string, reason = 'completed'): Promise<{ call_id: string; status: string }> {
    const entry = this.calls.get(callId)
    if (entry?.mode === 'baileys_voip' && this.voip) {
      try {
        this.voip.endCall(callId, reason)
      } catch (err) {
        console.warn('[voip] endCall failed', err)
      }
    }
    await this.cleanupCall(callId, 'ended', reason)
    return { call_id: callId, status: 'ended' }
  }

  setMuted(callId: string, muted: boolean): { call_id: string; muted: boolean } {
    const entry = this.calls.get(callId)
    if (!entry) {
      throw new Error(`Call not found: ${callId}`)
    }
    entry.bridge.setMuted(muted)
    if (entry.session?.mute) {
      try {
        entry.session.mute(muted)
      } catch {}
    }
    return { call_id: callId, muted }
  }

  async simulateIncomingCall(opts: {
    from: string
    wavBase64?: string
    callId?: string
  }): Promise<ManagedCallInfo> {
    const callId = opts.callId || `SIM-${randomUUID().replace(/-/g, '').slice(0, 12).toUpperCase()}`
    const from = this.resolvePhone(opts.from)
    const simSamples16k = opts.wavBase64 ? decodeWav16kMono(Buffer.from(opts.wavBase64, 'base64')) : undefined
    const bridge = new WebRtcCallBridge(
      callId,
      this.cfg,
      (wav, durationMs, startedAtIso) => {
        void this.emitUtterance(callId, from, wav, durationMs, 'client', startedAtIso)
      },
      (wav, durationMs, startedAtIso) => {
        void this.emitUtterance(callId, from, wav, durationMs, 'manager', startedAtIso)
      }
    )

    const entry: ManagedCall = {
      callId,
      from,
      mode: 'simulation',
      status: 'ringing',
      isVideo: false,
      isWaiting: false,
      startedAt: new Date().toISOString(),
      session: null,
      bridge,
      simSamples16k,
    }
    this.calls.set(callId, entry)

    await this.postCallWebhook({
      event: 'call.incoming',
      call_id: callId,
      from,
      is_video: false,
      is_waiting: false,
      provider: 'baileys_voip',
      mode: 'simulation',
    })

    return this.listCalls().find((c) => c.call_id === callId)!
  }

  injectCallerAudio(
    callId: string,
    wavBase64: string,
    speaker: 'client' | 'manager' = 'client'
  ): { call_id: string; samples: number; speaker: string } {
    const entry = this.calls.get(callId)
    if (!entry) {
      throw new Error(`Call not found: ${callId}`)
    }
    const buf = Buffer.from(wavBase64, 'base64')
    const samples = decodeWav16kMono(buf)
    if (speaker === 'manager') {
      const durationMs = Math.round((samples.length / this.cfg.sampleRate) * 1000)
      void this.emitUtterance(callId, entry.from, buf, durationMs, 'manager')
      return { call_id: callId, samples: samples.length, speaker: 'manager' }
    }
    this.startSimPlayback(entry, samples)
    return { call_id: callId, samples: samples.length, speaker: 'client' }
  }

  private async handleIncomingWhatsAppCall(session: any): Promise<void> {
    const callId = String(session.callId || '')
    const rawFrom = String(session.callerPn || session.phoneNumber || session.peerJid || '')
    const from = this.resolvePhone(rawFrom)
    if (!callId) return

    console.log(`[voip] incoming WhatsApp call ${callId} from ${from} (${rawFrom})`)

    const bridge = new WebRtcCallBridge(
      callId,
      this.cfg,
      (wav, durationMs, startedAtIso) => {
        void this.emitUtterance(callId, from, wav, durationMs, 'client', startedAtIso)
      },
      (wav, durationMs, startedAtIso) => {
        void this.emitUtterance(callId, from, wav, durationMs, 'manager', startedAtIso)
      }
    )

    const entry: ManagedCall = {
      callId,
      from,
      mode: 'baileys_voip',
      status: 'ringing',
      isVideo: Boolean(session.isVideo),
      isWaiting: Boolean(session.isWaiting),
      startedAt: new Date().toISOString(),
      session,
      bridge,
    }
    this.calls.set(callId, entry)

    // Hook startAudio BEFORE acceptCall so outbound audio drains our live browser WebRTC mic queue.
    session.startAudio = (
      sampleRate: number,
      channels: number,
      framesPerChunk: number,
      sendAudioChunkFn: (chunk: Float32Array) => void
    ) => {
      if (session.ended || entry.pacingTimer) return
      session._isAudioStreaming = true
      session._confirmAudioReady?.()
      session._confirmStreaming?.()
      const intervalMs = Math.max(10, Math.round(((framesPerChunk || 320) / (sampleRate || 16000)) * 1000))
      const frames = (framesPerChunk || 320) * (channels || 1)
      let nextAt = Date.now()
      const tick = () => {
        if (session.ended || !this.calls.has(callId)) {
          entry.pacingTimer = null
          return
        }
        try {
          sendAudioChunkFn(bridge.drainOutboundChunk(frames))
        } catch {}
        nextAt += intervalMs
        const delay = Math.max(0, nextAt - Date.now())
        entry.pacingTimer = setTimeout(tick, delay)
      }
      entry.pacingTimer = setTimeout(tick, intervalMs)
    }

    session.stopAudio = () => {
      session._isAudioStreaming = false
      if (entry.pacingTimer) {
        clearTimeout(entry.pacingTimer)
        entry.pacingTimer = null
      }
    }

    session.on('audio', (pcm: Float32Array) => {
      bridge.pushCallerPcm16k(pcm)
    })

    session.on('stateChange', (status: string) => {
      entry.status = String(status || entry.status)
      void this.postCallWebhook({
        event: 'call.state',
        call_id: callId,
        from,
        status: entry.status,
        mode: 'baileys_voip',
      })
    })

    session.on('ended', (reason: string) => {
      void this.cleanupCall(callId, 'ended', String(reason || 'ended'))
    })

    await this.postCallWebhook({
      event: 'call.incoming',
      call_id: callId,
      from,
      is_video: entry.isVideo,
      is_waiting: entry.isWaiting,
      provider: 'baileys_voip',
      mode: 'baileys_voip',
    })
  }

  private startSimPlayback(entry: ManagedCall, samples: Float32Array): void {
    if (entry.simTimer) {
      clearTimeout(entry.simTimer)
      entry.simTimer = null
    }
    const chunkSize = this.cfg.framesPerChunk // 320
    const intervalMs = Math.round((chunkSize / this.cfg.sampleRate) * 1000) // 20 ms
    let offset = 0
    let nextAt = Date.now() + 250 // slight settle time for browser ICE DTLS handshake

    const step = () => {
      if (!this.calls.has(entry.callId)) return
      if (offset >= samples.length) {
        // Send 1.2s of trailing silence so VAD closes the final utterance naturally.
        const silenceEnd = offset + this.cfg.sampleRate * 1.2
        const sendSilence = () => {
          if (!this.calls.has(entry.callId) || offset >= silenceEnd) {
            entry.bridge.flushVad()
            entry.simTimer = null
            return
          }
          entry.bridge.pushCallerPcm16k(new Float32Array(chunkSize))
          offset += chunkSize
          entry.simTimer = setTimeout(sendSilence, intervalMs)
        }
        entry.simTimer = setTimeout(sendSilence, intervalMs)
        return
      }
      const end = Math.min(offset + chunkSize, samples.length)
      const slice = new Float32Array(chunkSize)
      slice.set(samples.subarray(offset, end))
      entry.bridge.pushCallerPcm16k(slice)
      offset = end
      nextAt += intervalMs
      entry.simTimer = setTimeout(step, Math.max(0, nextAt - Date.now()))
    }
    entry.simTimer = setTimeout(step, 250)
  }

  private async cleanupCall(callId: string, status: string, reason: string): Promise<void> {
    const entry = this.calls.get(callId)
    if (!entry) return
    this.calls.delete(callId)
    if (entry.simTimer) {
      clearTimeout(entry.simTimer)
      entry.simTimer = null
    }
    if (entry.pacingTimer) {
      clearTimeout(entry.pacingTimer)
      entry.pacingTimer = null
    }
    const finalStats = { ...entry.bridge.stats }
    await entry.bridge.close()
    await this.postCallWebhook({
      event: 'call.ended',
      call_id: callId,
      from: entry.from,
      status,
      reason,
      mode: entry.mode,
      stats: finalStats,
    })
  }

  private async emitUtterance(
    callId: string,
    from: string,
    wav: Buffer,
    durationMs: number,
    speaker: 'client' | 'manager' = 'client',
    startedAtIso?: string
  ): Promise<void> {
    await this.postCallWebhook({
      event: 'call.utterance',
      call_id: callId,
      from,
      speaker,
      duration_ms: durationMs,
      started_at: startedAtIso || new Date(Date.now() - durationMs).toISOString(),
      wav_base64: wav.toString('base64'),
    })
  }

  private async postCallWebhook(payload: Record<string, unknown>): Promise<void> {
    try {
      const response = await fetch(`${this.apiUrl}/webhooks/call`, {
        method: 'POST',
        signal: AbortSignal.timeout(8000),
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (!response.ok) {
        console.error(`[voip] webhook ${response.status} for ${String(payload.event)}`)
      }
    } catch (err) {
      console.error('[voip] webhook failed', err)
    }
  }
}
