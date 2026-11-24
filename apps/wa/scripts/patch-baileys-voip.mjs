import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'

const targets = [
  resolve(process.cwd(), 'node_modules/@innovatorssoft/baileys/lib/Voip/call-manager.mjs'),
  resolve(process.cwd(), 'node_modules/@innovatorssoft/baileys/lib/Voip/index.mjs'),
]

const OLD =
  'const activeStatuses = ["accepted", "connected", "audio_ready", "streaming"];\n' +
  '                    if (!activeStatuses.includes(session.status)) {'

const NEW =
  'const activeStatuses = ["initiating", "signaling", "ringing", "incoming_ringing", "waiting", "accepted", "connected", "audio_ready", "streaming"];\n' +
  '                    if (!activeStatuses.includes(session.status)) {'

let patched = 0
for (const file of targets) {
  if (!existsSync(file)) continue
  const content = readFileSync(file, 'utf8')
  if (content.includes('"incoming_ringing", "waiting"')) {
    continue
  }
  if (!content.includes(OLD)) {
    // Also tolerate different indentation on the eventType === 2 guard
    const regex =
      /(\/\/ Don't tear down an already-accepted\/streaming call via a generic WASM end event\.\s*const activeStatuses = )\[[^\]]+\];/g
    if (regex.test(content)) {
      const updated = content.replace(
        regex,
        '$1["initiating", "signaling", "ringing", "incoming_ringing", "waiting", "accepted", "connected", "audio_ready", "streaming"];'
      )
      writeFileSync(file, updated, 'utf8')
      patched += 1
      console.log(`[patch-baileys-voip] patched (regex) ${file}`)
    } else {
      console.warn(`[patch-baileys-voip] pattern not found in ${file}`)
    }
    continue
  }
  const updated = content.replaceAll(OLD, NEW)
  writeFileSync(file, updated, 'utf8')
  patched += 1
  console.log(`[patch-baileys-voip] patched ${file}`)
}

console.log(`[patch-baileys-voip] done (updated ${patched} file(s))`)
