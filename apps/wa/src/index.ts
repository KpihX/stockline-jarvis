/**
 * Minimal WhatsApp listener for Stockline, inspired by the whats-proxy daemon.
 *
 * Responsibilities, copied from the essential parts of whats-proxy:
 *  - persist Baileys auth state on a mounted volume (useMultiFileAuthState)
 *  - receive inbound messages through messages.upsert
 *  - extract text, voice and image into a Signal
 *  - POST the Signal to the FastAPI webhook
 *  - expose a tiny HTTP endpoint for sending acknowledgements
 *
 * This package is self-contained and does not import from any external repo.
 */

import { createServer, type IncomingMessage, type ServerResponse } from 'node:http'
import { existsSync, mkdirSync, readdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import {
  type AnyMessageContent,
  DisconnectReason,
  downloadMediaMessage,
  fetchLatestBaileysVersion,
  makeWASocket,
  useMultiFileAuthState,
} from '@innovatorssoft/baileys'
import { Boom } from '@hapi/boom'
import QRCode from 'qrcode'
import { VoipBridgeManager } from './voip.js'
import type { BridgeConfig } from './webrtc-bridge.js'

const API_URL = process.env.AI_URL || process.env.STOCKLINE_API_URL || 'http://ai:4100'
const STATE_DIR = process.env.WHATS_PROXY_STATE_DIR || '/wa-state'
const PORT = Number(process.env.WA_PORT || 3001)
const PHONE = process.env.STOCKLINE_PHONE || ''

function loadCallsConfig(): {
  bridgeConfig: BridgeConfig
  maxConcurrentCalls: number
  pthreadPoolSize: number
} {
  const iceList = (process.env.ICE_SERVERS || 'stun:stun.l.google.com:19302')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)
  return {
    maxConcurrentCalls: Number(process.env.WA_MAX_CONCURRENT_CALLS ?? 2),
    pthreadPoolSize: Number(process.env.WA_PTHREAD_POOL_SIZE ?? 4),
    bridgeConfig: {
      sampleRate: Number(process.env.WA_SAMPLE_RATE ?? 16000),
      webrtcRate: Number(process.env.WA_WEBRTC_RATE ?? 48000),
      channels: 1,
      framesPerChunk: Number(process.env.WA_FRAMES_PER_CHUNK ?? 320),
      vadRmsThreshold: Number(process.env.WA_VAD_RMS_THRESHOLD ?? 0.012),
      vadSilenceMs: Number(process.env.WA_VAD_SILENCE_MS ?? 1000),
      vadMaxUtteranceMs: Number(process.env.WA_VAD_MAX_UTTERANCE_MS ?? 12000),
      icePortMin: Number(process.env.WA_ICE_PORT_MIN ?? 40000),
      icePortMax: Number(process.env.WA_ICE_PORT_MAX ?? 40020),
      iceServers: iceList.length ? iceList : ['stun:stun.l.google.com:19302'],
    },
  }
}

interface Signal {
  evenement_id: string
  capture_le: string
  canal: string
  actor_ref: string
  modality: string
  texte: string
  cNumber: string
  message_id: string
  media_path?: string
}

interface SendRequest {
  jid: string
  text: string
}

let sock: ReturnType<typeof makeWASocket> | null = null
let currentQr: { dataUrl: string; at: number } | null = null
let status = 'disconnected'
let manualDisconnect = false
let reconnectTimer: NodeJS.Timeout | null = null
let socketGen = 0
let connectInFlight: Promise<void> | null = null
const seenMessageIds = new Set<string>()

process.on('uncaughtException', (err) => {
  console.error('[wa] uncaughtException:', err)
})
process.on('unhandledRejection', (reason) => {
  console.error('[wa] unhandledRejection:', reason)
})

function clearAuthFiles(): void {
  if (!existsSync(STATE_DIR)) return
  for (const name of readdirSync(STATE_DIR)) {
    try {
      rmSync(join(STATE_DIR, name), { recursive: true, force: true })
    } catch (err) {
      console.warn('[wa] failed to remove auth file', name, err)
    }
  }
}

function canonicalPhone(value: string): string {
  const userPart = value.split('@')[0].split(':')[0]
  return userPart.replace(/[^0-9]/g, '')
}

function resolvePhoneFromJid(jid: string): string {
  if (!jid) return ''
  if (jid.endsWith('@lid')) {
    const lid = canonicalPhone(jid)
    const reverseFile = join(STATE_DIR, `lid-mapping-${lid}_reverse.json`)
    if (existsSync(reverseFile)) {
      try {
        const mapped = JSON.parse(readFileSync(reverseFile, 'utf8'))
        if (typeof mapped === 'string' && mapped.trim()) {
          return canonicalPhone(mapped)
        }
      } catch (error) {
        console.error('[wa] lid reverse lookup failed', error)
      }
    }
    return lid
  }
  return canonicalPhone(jid)
}

async function resolvePhoneFromJidAsync(jid: string): Promise<string> {
  if (!jid) return ''
  if (jid.endsWith('@lid')) {
    try {
      const pn = await (sock as any)?.signalRepository?.lidMapping?.getPNForLID?.(jid)
      if (typeof pn === 'string' && pn.trim()) {
        return canonicalPhone(pn)
      }
    } catch {}
  }
  return resolvePhoneFromJid(jid)
}

function resolveSenderPhone(key: any): string {
  const alt = key?.remoteJidAlt || key?.senderPn || ''
  if (typeof alt === 'string' && alt.endsWith('@s.whatsapp.net')) {
    return canonicalPhone(alt)
  }
  return resolvePhoneFromJid(String(key?.remoteJid || ''))
}

const callsCfg = loadCallsConfig()
const voipManager = new VoipBridgeManager({
  apiUrl: API_URL,
  bridgeConfig: callsCfg.bridgeConfig,
  maxConcurrentCalls: callsCfg.maxConcurrentCalls,
  pthreadPoolSize: callsCfg.pthreadPoolSize,
  resolvePhone: resolvePhoneFromJid,
})

function unwrapMessage(raw: any): any {
  if (!raw) return raw
  if (raw.ephemeralMessage?.message) return unwrapMessage(raw.ephemeralMessage.message)
  if (raw.viewOnceMessage?.message) return unwrapMessage(raw.viewOnceMessage.message)
  if (raw.viewOnceMessageV2?.message) return unwrapMessage(raw.viewOnceMessageV2.message)
  return raw
}

function extract(rawMessage: any): { text: string; modality: string } {
  const message = unwrapMessage(rawMessage)
  if (message?.conversation) return { text: message.conversation, modality: 'text' }
  if (message?.extendedTextMessage?.text) {
    return { text: message.extendedTextMessage.text, modality: 'text' }
  }
  if (message?.audioMessage || message?.voiceMessage) {
    return { text: '[voice]', modality: 'audio' }
  }
  if (message?.imageMessage) {
    const caption = String(message.imageMessage.caption || '').trim()
    return { text: caption || '[image]', modality: 'image' }
  }
  return { text: '', modality: 'unknown' }
}

function notifyWaStatus(): void {
  void fetch(`${API_URL}/webhooks/call`, {
    method: 'POST',
    signal: AbortSignal.timeout(4000),
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      event: 'wa.status',
      call_id: '__wa__',
      status,
      phone: sock?.user?.id || '',
      qr_ready: currentQr !== null,
    }),
  }).catch(() => {})
}

async function postSignal(signal: Signal): Promise<void> {
  for (let attempt = 1; attempt <= 2; attempt++) {
    try {
      const response = await fetch(`${API_URL}/webhooks/whatsapp`, {
        method: 'POST',
        signal: AbortSignal.timeout(8000),
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(signal),
      })
      if (response.ok) return
      console.error(`[wa] webhook ${response.status} (attempt ${attempt})`)
    } catch (error) {
      console.error(`[wa] webhook failed (attempt ${attempt})`, error)
    }
    if (attempt === 1) await new Promise((r) => setTimeout(r, 800))
  }
}

async function connect(expectedGen = socketGen): Promise<void> {
  if (connectInFlight) {
    try {
      await connectInFlight
    } catch {}
    if (expectedGen !== socketGen || manualDisconnect) return
  }
  connectInFlight = (async () => {
    try {
      mkdirSync(STATE_DIR, { recursive: true })
      const { state, saveCreds } = await useMultiFileAuthState(STATE_DIR)
      let version: [number, number, number] = [2, 3000, 1027934701]
      try {
        const fetched = await Promise.race([
          fetchLatestBaileysVersion(),
          new Promise<never>((_, reject) =>
            setTimeout(() => reject(new Error('fetchLatestBaileysVersion timeout')), 5000)
          ),
        ])
        if (fetched?.version) version = fetched.version
      } catch (err) {
        console.warn('[wa] fetchLatestBaileysVersion fallback:', err)
      }

      if (expectedGen !== socketGen || manualDisconnect) return

      const createWASocket = ((makeWASocket as any)?.default ?? makeWASocket) as typeof makeWASocket
      const activeSock = createWASocket({
        version,
        auth: state,
        browser: ['J.A.R.V.I.S ERP', 'Chrome', '1.0.0'],
        voip: {
          maxConcurrentCalls: callsCfg.maxConcurrentCalls,
          pthreadPoolSize: callsCfg.pthreadPoolSize,
        },
      } as any)
      sock = activeSock
      const myGen = expectedGen
      activeSock.ev.on('creds.update', saveCreds)

      activeSock.ev.on('connection.update', (update: any) => {
        if (myGen !== socketGen || sock !== activeSock) return
        const { connection, lastDisconnect, qr } = update
        if (qr) {
          status = 'qr_pending'
          QRCode.toDataURL(qr)
            .then((dataUrl: string) => {
              if (myGen !== socketGen) return
              currentQr = { dataUrl, at: Date.now() }
              console.log('[wa] QR ready for pairing')
              notifyWaStatus()
            })
            .catch((error: unknown) => console.error('[wa] QR render failed', error))
        }
        if (connection === 'close') {
          if (sock === activeSock) sock = null
          status = 'disconnected'
          currentQr = null
          notifyWaStatus()
          const code = (lastDisconnect?.error as Boom)?.output?.statusCode
          console.warn(`[wa] connection closed code=${code ?? 'unknown'} manual=${manualDisconnect}`)
          if (code === DisconnectReason.loggedOut) {
            clearAuthFiles()
            return
          }
          if (!manualDisconnect && !reconnectTimer) {
            const genAtSchedule = socketGen
            reconnectTimer = setTimeout(() => {
              reconnectTimer = null
              if (!manualDisconnect && genAtSchedule === socketGen) void connect(genAtSchedule)
            }, 3000)
          }
        }
        if (connection === 'open') {
          status = 'connected'
          currentQr = null
          console.log(`[wa] connected as ${activeSock.user?.id || '?'}`)
          notifyWaStatus()
          void voipManager.attachSocket(activeSock)
        }
      })

      activeSock.ev.on('messages.upsert', async ({ messages, type }: any) => {
        if (myGen !== socketGen) return
    if (type !== 'notify') return
    for (const message of messages) {
      if (!message.message || message.key.fromMe) continue
      const msgId = String(message.key.id || '')
      if (msgId) {
        if (seenMessageIds.has(msgId)) {
          console.log(`[wa] skipping duplicate message ${msgId}`)
          continue
        }
        seenMessageIds.add(msgId)
        if (seenMessageIds.size > 2000) {
          const oldest = seenMessageIds.values().next().value
          if (oldest) seenMessageIds.delete(oldest)
        }
      }
      const jid = String(message.key.remoteJid || '')
      if (!jid || jid.endsWith('@g.us') || jid.endsWith('@broadcast') || jid === 'status@broadcast') {
        continue
      }
      const cNumber = await resolvePhoneFromJidAsync(
        String(message.key?.remoteJidAlt || message.key?.senderPn || message.key?.remoteJid || '')
      )
      if (!cNumber) continue
      if (PHONE && cNumber !== canonicalPhone(PHONE)) continue
      const { text, modality } = extract(message.message)
      if (!text || modality === 'unknown') continue
      let mediaPath = ''
      if (modality === 'audio' || modality === 'image') {
        try {
          const safeId = (msgId || `evt_${Date.now()}`).replace(/[^a-zA-Z0-9_-]/g, '')
          const ext = modality === 'audio' ? 'ogg' : 'png'
          mediaPath = `/tmp/wa_media_${safeId}.${ext}`
          const buffer = await downloadMediaMessage(message, 'buffer', {})
          writeFileSync(mediaPath, buffer as Buffer)
          console.log(
            `[wa] saved ${modality} media (${(buffer as Buffer).length} bytes) to ${mediaPath}`
          )
        } catch (error) {
          console.error(`[wa] ${modality} media download failed`, error)
          mediaPath = ''
        }
      }
      const signal: Signal = {
        evenement_id: msgId || `evt_${Date.now()}`,
        capture_le: new Date().toISOString(),
        canal: 'whatsapp',
        actor_ref: cNumber,
        modality,
        texte: text,
        cNumber,
        message_id: msgId,
        media_path: mediaPath,
      }
        console.log(
          `[wa] posting signal id=${signal.evenement_id} phone=${cNumber} modality=${modality} media=${mediaPath || 'none'}`
        )
        await postSignal(signal)
      }
    })
    } finally {
      connectInFlight = null
    }
  })()
  return connectInFlight
}

function sendJson(response: ServerResponse, code: number, body: unknown): void {
  response.writeHead(code, { 'Content-Type': 'application/json' })
  response.end(JSON.stringify(body))
}

function readBody(request: IncomingMessage): Promise<string> {
  return new Promise((resolve) => {
    let data = ''
    request.on('data', (chunk) => (data += chunk))
    request.on('end', () => resolve(data))
  })
}

const server = createServer(async (request, response) => {
  if (request.method === 'GET' && request.url === '/health') {
    sendJson(response, 200, { status: 'ok', connected: sock !== null })
    return
  }
  if (request.method === 'GET' && request.url === '/status') {
    sendJson(response, 200, {
      status,
      phone: sock?.user?.id || '',
      qr_ready: currentQr !== null,
    })
    return
  }
  if (request.method === 'GET' && request.url === '/qr') {
    if (!currentQr || Date.now() - currentQr.at > 300_000) {
      sendJson(response, 404, { error: 'no QR available' })
      return
    }
    sendJson(response, 200, { qr: currentQr.dataUrl })
    return
  }
  if (request.method === 'POST' && request.url === '/connect') {
    let reset = false
    try {
      const raw = await readBody(request)
      if (raw.trim()) reset = Boolean(JSON.parse(raw)?.reset)
    } catch {}
    manualDisconnect = false
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    if (reset || status !== 'connected' || !sock) {
      socketGen += 1
      const prev = sock
      sock = null
      currentQr = null
      status = 'connecting'
      try {
        prev?.end?.(undefined)
      } catch {}
      if (reset) clearAuthFiles()
      const targetGen = socketGen
      void connect(targetGen)
    }
    sendJson(response, 200, { status })
    return
  }
  if (request.method === 'POST' && request.url === '/disconnect') {
    manualDisconnect = true
    socketGen += 1
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    const prev = sock
    sock = null
    status = 'disconnected'
    currentQr = null
    try {
      if (prev?.logout) {
        await Promise.race([
          prev.logout(),
          new Promise((resolve) => setTimeout(resolve, 3500)),
        ])
      }
    } catch {}
    try {
      prev?.end?.(undefined)
    } catch {}
    clearAuthFiles()
    sendJson(response, 200, { status: 'disconnected' })
    return
  }
  if (request.method === 'POST' && request.url === '/send') {
    try {
      const body = JSON.parse(await readBody(request)) as SendRequest
      if (!sock || status !== 'connected') {
        sendJson(response, 503, { error: 'not connected' })
        return
      }
      const rawJid = String(body.jid || '').trim()
      const targetJid = rawJid.includes('@') ? rawJid : `${canonicalPhone(rawJid)}@s.whatsapp.net`
      const content: AnyMessageContent = { text: body.text }
      await sock.sendMessage(targetJid, content)
      console.log(`[wa] sent notification to ${targetJid}`)
      sendJson(response, 200, { status: 'sent', jid: targetJid })
    } catch (error) {
      console.error('[wa] /send failed', error)
      sendJson(response, 502, { error: String(error) })
    }
    return
  }
  if (request.method === 'GET' && request.url === '/calls') {
    sendJson(response, 200, { items: voipManager.listCalls() })
    return
  }
  if (request.method === 'POST' && request.url === '/call/accept') {
    try {
      const body = JSON.parse(await readBody(request)) as { call_id: string; sdp_offer: string }
      const result = await voipManager.acceptCall(String(body.call_id || ''), String(body.sdp_offer || ''))
      sendJson(response, 200, result)
    } catch (error) {
      const msg = error instanceof Error ? error.message : String(error)
      console.error('[wa] /call/accept failed', msg)
      sendJson(response, msg.includes('Call not found') ? 404 : 400, { error: msg })
    }
    return
  }
  if (request.method === 'POST' && request.url === '/call/reject') {
    try {
      const body = JSON.parse(await readBody(request)) as { call_id: string; reason?: string }
      const result = await voipManager.rejectCall(String(body.call_id || ''), body.reason || 'declined')
      sendJson(response, 200, result)
    } catch (error) {
      sendJson(response, 400, { error: String(error) })
    }
    return
  }
  if (request.method === 'POST' && request.url === '/call/hangup') {
    try {
      const body = JSON.parse(await readBody(request)) as { call_id: string; reason?: string }
      const result = await voipManager.hangupCall(String(body.call_id || ''), body.reason || 'completed')
      sendJson(response, 200, result)
    } catch (error) {
      sendJson(response, 400, { error: String(error) })
    }
    return
  }
  if (request.method === 'POST' && request.url === '/call/mute') {
    try {
      const body = JSON.parse(await readBody(request)) as { call_id: string; muted: boolean }
      const result = voipManager.setMuted(String(body.call_id || ''), Boolean(body.muted))
      sendJson(response, 200, result)
    } catch (error) {
      sendJson(response, 400, { error: String(error) })
    }
    return
  }
  if (request.method === 'POST' && request.url === '/call/simulate') {
    try {
      const body = JSON.parse(await readBody(request)) as {
        from: string
        wav_base64?: string
        call_id?: string
      }
      const result = await voipManager.simulateIncomingCall({
        from: String(body.from || ''),
        wavBase64: body.wav_base64,
        callId: body.call_id,
      })
      sendJson(response, 200, result)
    } catch (error) {
      console.error('[wa] /call/simulate failed', error)
      sendJson(response, 400, { error: String(error) })
    }
    return
  }
  if (request.method === 'POST' && request.url === '/call/inject-audio') {
    try {
      const body = JSON.parse(await readBody(request)) as {
        call_id: string
        wav_base64: string
        speaker?: 'client' | 'manager'
      }
      const result = voipManager.injectCallerAudio(
        String(body.call_id || ''),
        String(body.wav_base64 || ''),
        body.speaker === 'manager' ? 'manager' : 'client'
      )
      sendJson(response, 200, result)
    } catch (error) {
      sendJson(response, 400, { error: String(error) })
    }
    return
  }
  sendJson(response, 404, { error: 'not found' })
})

server.listen(PORT, '0.0.0.0', () => {
  console.log(`[wa] ack API listening on ${PORT}`)
  void fetch(`${API_URL}/webhooks/call`, {
    method: 'POST',
    signal: AbortSignal.timeout(5000),
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ event: 'wa.boot', call_id: '__boot__' }),
  }).catch(() => {})
  void connect()
})
