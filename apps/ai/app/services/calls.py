"""WhatsApp VoIP Call Desk & Baileys bridge coordinator (Manager & Admin only).

Bridges `apps/wa` (Baileys VoIP + pure-TS WebRTC Opus <-> 16 kHz PCM + VAD) with `apps/ai`
(Soniox/Mock STT + ElevenLabs/Mock WAV simulation + Jev routing + live J.A.R.V.I.S ERP copilot).
Persists call sessions and WhatsApp phone <-> ERP client bindings in SQLite (`$AI_STATE_DIR/calls.db`).
"""

from __future__ import annotations

import asyncio
import base64
import json
import math
import os
import re
import sqlite3
import struct
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from app.agent import run_agent
from app.agent.prompts import build_session_block
from app.clients import get_llm_client, get_stt_client
from app.clients.http import http_client
from app.config import settings
from app.lexicon.runtime import annotate
from app.policy import Caller
from app.schemas import ChatMessage, DoneEvent, ErrorEvent, TextEvent, ToolResultEvent
from app.services import jev_router
from app.services.vocabulary import stt_hint
from app.tools import all_tools
from app.tools.erp import ErpClient

_SILENCE_MARKERS = {"[BLANK_AUDIO]", "(silence)", "[silence]", "(musique)", "[Music]"}
_CALL_STT_HINT = (
    "Alpes Restauration, Le Refuge Payet, 1er décembre, mi-décembre, mi-avril, décembre, janvier, "
    "mets-moi, deux cents kilos, vingt kilos, frites surgelées, raclette tranchée, raclette en meule, "
    "crème fraîche, crème liquide, reblochon fermier, confirme la commande, ERP"
)
_STT_HOMOPHONES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(?:1er|premier)\s+d['’]exemples?\b", re.IGNORECASE), "1er décembre"),
    (re.compile(r"\b(\d{1,2})\s+d['’]exemples?\b", re.IGNORECASE), r"\1 décembre"),
    (re.compile(r"\bmi[- ]exemples?\b", re.IGNORECASE), "mi-décembre"),
    (re.compile(r"\b(?:1000|mille)\s+exemples?\b", re.IGNORECASE), "mi-décembre"),
)


def clean_call_transcript(text: str) -> str:
    """Fix narrow telephone-codec homophones verified on live 16 kHz French calls without altering valid names."""
    out = text
    for pattern, repl in _STT_HOMOPHONES:
        out = pattern.sub(repl, out)
    return out


_calls: dict[str, dict[str, Any]] = {}
_pending_sim_texts: dict[str, list[str]] = {}
_subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
_stt_sem = asyncio.Semaphore(4)
_copilot_locks: dict[str, asyncio.Lock] = {}
_copilot_versions: dict[str, int] = {}
_copilot_tasks: dict[str, asyncio.Task[Any]] = {}


def _wa_url(path: str = "") -> str:
    base = (os.environ.get("WA_URL") or "http://localhost:3001").rstrip("/")
    return f"{base}{path}"


def _db_path() -> Path:
    base = Path(os.environ.get("AI_STATE_DIR") or ".state")
    base.mkdir(parents=True, exist_ok=True)
    return base / "calls.db"


def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(_db_path(), check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS call_sessions (
            call_id TEXT PRIMARY KEY,
            phone_number TEXT NOT NULL,
            client_id TEXT NOT NULL DEFAULT '',
            client_name TEXT NOT NULL DEFAULT '',
            known_client INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'ringing',
            mode TEXT NOT NULL DEFAULT 'baileys_voip',
            started_at TEXT NOT NULL,
            ended_at TEXT NOT NULL DEFAULT '',
            reason TEXT NOT NULL DEFAULT '',
            muted INTEGER NOT NULL DEFAULT 0,
            committed INTEGER NOT NULL DEFAULT 0,
            transcripts_json TEXT NOT NULL DEFAULT '[]',
            linked_commands_json TEXT NOT NULL DEFAULT '[]',
            warnings_json TEXT NOT NULL DEFAULT '[]',
            copilot_note TEXT NOT NULL DEFAULT '',
            stats_json TEXT NOT NULL DEFAULT '{}',
            updated_at REAL NOT NULL
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS phone_client_map (
            phone_digits TEXT PRIMARY KEY,
            client_id TEXT NOT NULL,
            client_name TEXT NOT NULL DEFAULT '',
            updated_at REAL NOT NULL
        )
        """
    )
    return con


def _digits(value: str) -> str:
    head = (value or "").split("@", 1)[0].split(":", 1)[0]
    return "".join(ch for ch in head if ch.isdigit())


def _norm_fr_tail(digits: str) -> str:
    if not digits:
        return ""
    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith("33") and len(digits) == 11:
        return digits[2:]
    if digits.startswith("0") and len(digits) == 10:
        return digits[1:]
    return digits[-9:] if len(digits) >= 9 else digits


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "callId": row["call_id"],
        "phoneNumber": row["phone_number"],
        "clientId": row["client_id"],
        "clientName": row["client_name"],
        "knownClient": bool(row["known_client"]),
        "status": row["status"],
        "mode": row["mode"],
        "startedAt": row["started_at"],
        "endedAt": row["ended_at"] or None,
        "reason": row["reason"] or None,
        "muted": bool(row["muted"]),
        "committed": bool(row["committed"]),
        "transcripts": json.loads(row["transcripts_json"] or "[]"),
        "linkedCommands": json.loads(row["linked_commands_json"] or "[]"),
        "warnings": json.loads(row["warnings_json"] or "[]"),
        "copilotNote": row["copilot_note"] or "",
        "stats": json.loads(row["stats_json"] or "{}"),
    }


def _save_call(rec: dict[str, Any]) -> None:
    try:
        with _conn() as con:
            con.execute(
                """
                INSERT INTO call_sessions (
                    call_id, phone_number, client_id, client_name, known_client, status, mode,
                    started_at, ended_at, reason, muted, committed,
                    transcripts_json, linked_commands_json, warnings_json, copilot_note, stats_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(call_id) DO UPDATE SET
                    phone_number=excluded.phone_number,
                    client_id=excluded.client_id,
                    client_name=excluded.client_name,
                    known_client=excluded.known_client,
                    status=excluded.status,
                    mode=excluded.mode,
                    ended_at=excluded.ended_at,
                    reason=excluded.reason,
                    muted=excluded.muted,
                    committed=excluded.committed,
                    transcripts_json=excluded.transcripts_json,
                    linked_commands_json=excluded.linked_commands_json,
                    warnings_json=excluded.warnings_json,
                    copilot_note=excluded.copilot_note,
                    stats_json=excluded.stats_json,
                    updated_at=excluded.updated_at
                """,
                (
                    rec["callId"],
                    rec.get("phoneNumber", ""),
                    rec.get("clientId", ""),
                    rec.get("clientName", ""),
                    1 if rec.get("knownClient") else 0,
                    rec.get("status", "ringing"),
                    rec.get("mode", "baileys_voip"),
                    rec.get("startedAt", datetime.now(UTC).isoformat()),
                    rec.get("endedAt") or "",
                    rec.get("reason") or "",
                    1 if rec.get("muted") else 0,
                    1 if rec.get("committed") else 0,
                    json.dumps(rec.get("transcripts") or [], ensure_ascii=False),
                    json.dumps(rec.get("linkedCommands") or [], ensure_ascii=False),
                    json.dumps(rec.get("warnings") or [], ensure_ascii=False),
                    rec.get("copilotNote") or "",
                    json.dumps(rec.get("stats") or {}, ensure_ascii=False),
                    time.time(),
                ),
            )
    except Exception as exc:
        print(f"[calls] sqlite persist failed: {exc}", flush=True)


def list_phone_bindings() -> list[dict[str, str]]:
    try:
        with _conn() as con:
            rows = con.execute(
                "SELECT phone_digits, client_id, client_name FROM phone_client_map ORDER BY updated_at DESC"
            ).fetchall()
            return [{"phoneDigits": r["phone_digits"], "clientId": r["client_id"], "clientName": r["client_name"]} for r in rows]
    except Exception:
        return []


async def bind_phone_to_client(phone: str, client_id: str) -> dict[str, str]:
    digits = _digits(phone)
    if not digits:
        raise ValueError("Numéro WhatsApp invalide")
    erp = ErpClient("user", "WhatsApp Call Desk")
    cli = await erp.get(f"/api/clients/{client_id}")
    cname = str(cli.get("name") or client_id)
    with _conn() as con:
        con.execute(
            """
            INSERT INTO phone_client_map (phone_digits, client_id, client_name, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(phone_digits) DO UPDATE SET
                client_id=excluded.client_id,
                client_name=excluded.client_name,
                updated_at=excluded.updated_at
            """,
            (digits, client_id, cname, time.time()),
        )
    # Also update any active/recent call from this phone
    tail = _norm_fr_tail(digits)
    for rec in _calls.values():
        if _norm_fr_tail(rec.get("phoneNumber", "")) == tail:
            rec["clientId"] = client_id
            rec["clientName"] = cname
            rec["knownClient"] = True
            _save_call(rec)
    return {"phoneDigits": digits, "clientId": client_id, "clientName": cname}


async def _resolve_client_by_phone(phone: str) -> tuple[str, str, bool]:
    digits = _digits(phone)
    if not digits:
        return "", "Appelant inconnu", False
    tail = _norm_fr_tail(digits)
    try:
        with _conn() as con:
            rows = con.execute("SELECT phone_digits, client_id, client_name FROM phone_client_map").fetchall()
            for r in rows:
                if _norm_fr_tail(r["phone_digits"]) == tail:
                    return str(r["client_id"]), str(r["client_name"]), True
    except Exception:
        pass
    try:
        erp = ErpClient("voice_agent", "WhatsApp Call Desk")
        res = await erp.get("/api/clients", {"limit": 200})
        items = res if isinstance(res, list) else res.get("items", [])
        for c in items:
            for ct in c.get("contacts") or []:
                c_digits = _digits(str(ct.get("phone") or ""))
                if c_digits and _norm_fr_tail(c_digits) == tail:
                    return str(c["id"]), str(c["name"]), True
    except Exception as exc:
        print(f"[calls] ERP phone lookup failed: {exc}", flush=True)
    return "", digits, False


def subscribe() -> asyncio.Queue[dict[str, Any]]:
    q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    _subscribers.add(q)
    return q


def unsubscribe(q: asyncio.Queue[dict[str, Any]]) -> None:
    _subscribers.discard(q)


async def publish(event: dict[str, Any]) -> None:
    event.setdefault("ts", datetime.now(UTC).isoformat())
    for q in list(_subscribers):
        q.put_nowait(event)


def _format_dialogue(transcripts: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for t in sorted(transcripts, key=lambda item: int(item.get("seq", 0))):
        txt = str(t.get("text", "")).strip()
        if not txt:
            continue
        spk = "Gestionnaire" if str(t.get("speaker", "client")).lower() == "manager" else "Client"
        lines.append(f"[{spk}] {txt}")
    return "\n".join(lines).strip()


def _wrap_wav_16k_mono(pcm_bytes: bytes, sample_rate: int = 16000) -> bytes:
    data_len = len(pcm_bytes)
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + data_len,
        b"WAVE",
        b"fmt ",
        16,
        1,
        1,
        sample_rate,
        sample_rate * 2,
        2,
        16,
        b"data",
        data_len,
    )
    return header + pcm_bytes


def _synthetic_speech_wav(duration_s: float = 1.2, sample_rate: int = 16000) -> bytes:
    """Deterministic 16 kHz PCM WAV with speech-like amplitude bursts (> VAD threshold 0.012)."""
    n = int(sample_rate * duration_s)
    buf = bytearray(n * 2)
    for i in range(n):
        t = i / sample_rate
        # Modulate bursts between 0.05s and duration_s - 0.1s so VAD triggers and cleanly closes on silence
        env = 0.0 if (t < 0.05 or t > duration_s - 0.12) else (0.18 * abs(math.sin(2 * math.pi * 3.0 * t)))
        val = int(max(-32767, min(32767, env * math.sin(2 * math.pi * 240.0 * t) * 32767)))
        struct.pack_into("<h", buf, i * 2, val)
    return _wrap_wav_16k_mono(bytes(buf), sample_rate)


async def synthesize_wav_16k(text: str) -> bytes:
    """Synthesize French speech into 16 kHz mono 16-bit PCM WAV bytes without external ffmpeg/edge_tts."""
    tts_cfg = settings.tts
    if tts_cfg.provider == "elevenlabs" and tts_cfg.api_key:
        voice = tts_cfg.voice or "JBFqnCBsd6RMkjVDRZzb"
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice}/stream?output_format=pcm_16000"
        body = {
            "text": text,
            "model_id": tts_cfg.model or "eleven_flash_v2_5",
            "language_code": tts_cfg.language or "fr",
        }
        try:
            resp = await http_client().post(
                url,
                headers={"xi-api-key": tts_cfg.api_key, "content-type": "application/json"},
                json=body,
                timeout=15.0,
            )
            if resp.is_success and len(resp.content) > 640:
                return _wrap_wav_16k_mono(resp.content, 16000)
        except Exception as exc:
            print(f"[calls] ElevenLabs pcm_16000 failed, falling back to synthetic WAV: {exc}", flush=True)
    return _synthetic_speech_wav(max(0.9, min(2.2, len(text) / 35.0)))


async def _run_call_copilot(call_id: str) -> dict[str, Any] | None:
    """Run J.A.R.V.I.S over the live call dialogue to create/update draft ERP orders & warnings."""
    lock = _copilot_locks.setdefault(call_id, asyncio.Lock())
    async with lock:
        rec = _calls.get(call_id)
        if not rec:
            return None
        dialogue = _format_dialogue(rec.get("transcripts") or [])
        if not dialogue:
            return None

        client_id = rec.get("clientId") or None
        client_name = rec.get("clientName") or rec.get("phoneNumber") or "Client"
        caller = Caller(
            role="manager",
            client_id=client_id,
            actor_name=f"J.A.R.V.I.S · Appel {client_name}",
            verified=True,
        )
        session_block = await build_session_block(caller) if client_id else ""
        existing_cmds = ", ".join(f"{c.get('id')} ({c.get('number') or c.get('id')})" for c in (rec.get("linkedCommands") or []))
        prompt = (
            f"Appel téléphonique WhatsApp en cours avec {client_name}"
            + (f" ({client_id})" if client_id else f" (numéro {rec.get('phoneNumber', '?')}, client non encore associé)")
            + ".\n"
            + (f"Commandes déjà créées dans cet appel : {existing_cmds} — si le client ajoute ou modifie un article pour la même livraison, utilise `add_order_line(order_id='<id ord_...>')` avec l'identifiant technique `ord_...` ci-dessus au lieu de créer une nouvelle commande.\n" if existing_cmds else "")
            + "Voici la transcription en direct :\n"
            + f"{dialogue}\n\n"
            + "Consignes STRICTES pour le copilote en direct :\n"
            + "1. RÈGLE D'ABSTENTION (ZÉRO INVENTIONS) : n'appelle JAMAIS `create_draft_order` ni `add_order_line` tant que le client n'a pas nommé EXPLICITEMENT au moins un produit précis ET sa quantité (ou dit explicitement « comme d'habitude »). Si le client reste vague (« du fromage ou de la crème », simple salutation), ne touche PAS à l'ERP : consulte le stock/tarif (`search`, `get_product_stock`) et donne au gestionnaire la question de clarification exacte à poser.\n"
            + "2. Dès qu'un produit + quantité est clair, crée ou complète la pré-commande brouillon (`create_draft_order` / `add_order_line`). Ne confirme (`confirm_order`) que sur accord explicite dans le dialogue.\n"
            + "3. Réponds en 1 à 2 phrases ultra-courtes pour le commercial à l'écran : état du brouillon ou clarification attendue, prix négocié, et TOUTES les alertes `warnings` (`season_closed`, `unusual_quantity`, client bloqué)."
        )

        reply = ""
        agent_error = ""
        new_cmds: list[dict[str, Any]] = list(rec.get("linkedCommands") or [])
        new_warnings: list[dict[str, str]] = list(rec.get("warnings") or [])
        seen_ids = {c.get("id") for c in new_cmds if c.get("id")}
        seen_warns = {(w.get("code"), w.get("message")) for w in new_warnings}

        try:
            async for ev in run_agent(
                [ChatMessage(role="user", content=prompt)],
                llm=get_llm_client(),
                tools=all_tools(),
                mode="voice",
                actor_name=caller.actor_name,
                caller=caller,
                session_block=session_block,
            ):
                if isinstance(ev, TextEvent):
                    reply += ev.delta
                elif isinstance(ev, ToolResultEvent) and ev.ok and isinstance(ev.result, dict):
                    r = ev.result
                    if ev.name in ("create_draft_order", "add_order_line", "confirm_order", "get_order") and r.get("id"):
                        cid = str(r["id"])
                        cmd_obj = {
                            "id": cid,
                            "number": r.get("number") or cid,
                            "status": r.get("status") or "draft",
                            "deliveryDate": r.get("deliveryDate") or "",
                            "totalHt": r.get("totalHt") or 0,
                            "lineCount": len(r.get("lines") or []),
                        }
                        if cid in seen_ids:
                            new_cmds = [cmd_obj if c.get("id") == cid else c for c in new_cmds]
                        else:
                            seen_ids.add(cid)
                            new_cmds.append(cmd_obj)
                    for w in r.get("warnings") or []:
                        if isinstance(w, dict) and w.get("message"):
                            key = (str(w.get("code", "warning")), str(w["message"]))
                            if key not in seen_warns:
                                seen_warns.add(key)
                                new_warnings.append({"code": key[0], "message": key[1]})
                elif isinstance(ev, ErrorEvent):
                    agent_error = ev.message
                elif isinstance(ev, DoneEvent) and not reply and ev.message.content:
                    reply = ev.message.content
        except Exception as exc:
            print(f"[calls] copilot error for {call_id}: {exc}", flush=True)
            agent_error = str(exc) or type(exc).__name__

        if not reply.strip() and agent_error:
            reply = f"Copilote en difficulté ({agent_error}) — utilisez « Extraire vers ERP » ou « Confirmer »."

        rec["linkedCommands"] = new_cmds
        rec["warnings"] = new_warnings
        if reply.strip():
            rec["copilotNote"] = reply.strip()
        if new_cmds:
            rec["committed"] = True
        _save_call(rec)
        await publish(
            {
                "type": "call.copilot",
                "callId": call_id,
                "copilotNote": rec["copilotNote"],
                "linkedCommands": new_cmds,
                "warnings": new_warnings,
            }
        )
        return rec


async def _process_utterance(
    rec: dict[str, Any],
    call_id: str,
    seq: int,
    speaker: str,
    raw_wav: bytes,
    duration_ms: int,
) -> None:
    try:
        stt = get_stt_client()
        hint = await stt_hint(stt.name, _CALL_STT_HINT, rec.get("clientId") or None)
        if stt.name == "mock" and speaker == "client" and _pending_sim_texts.get(call_id):
            hint = _pending_sim_texts[call_id].pop(0)

        async with _stt_sem:
            text = (await stt.transcribe(raw_wav, "audio/wav", hint)).strip()

        if not text or text in _SILENCE_MARKERS:
            if speaker == "client" and _pending_sim_texts.get(call_id):
                text = _pending_sim_texts[call_id].pop(0)
            else:
                return

        text = clean_call_transcript(text)

        jev_ms: int | None = None
        jev_route: str | None = None
        if speaker == "client":
            t0_jev = time.perf_counter()
            route_task = asyncio.create_task(
                jev_router.route_turn(
                    text,
                    jev_router.TurnState(transcript=text, client_id=rec.get("clientId") or None, role="manager"),
                )
            )
            lex_notes = await annotate(text, rec.get("clientId") or None)
            try:
                route = await route_task
                jev_ms = round((time.perf_counter() - t0_jev) * 1000)
                jev_route = f"{route.intent}:{route.tools_needed}" if route.decided_by == "jev" else route.intent
            except Exception:
                pass
            if lex_notes:
                print(f"[calls] lexicon hint for {call_id}: {lex_notes}", flush=True)

        entry = {
            "id": f"{call_id}_{seq}",
            "seq": seq,
            "speaker": speaker,
            "text": text,
            "durationMs": duration_ms,
            "ts": datetime.now(UTC).isoformat(),
            **({"jevMs": jev_ms} if jev_ms is not None else {}),
            **({"jevRoute": jev_route} if jev_route else {}),
        }
        rec["transcripts"].append(entry)
        rec["transcripts"].sort(key=lambda t: int(t.get("seq", 0)))
        _save_call(rec)
        await publish({"type": "call.transcript", "callId": call_id, "entry": entry})

        if speaker == "client":
            _schedule_copilot(call_id)
    except Exception as exc:
        err_msg = f"STT error: {exc}"
        await publish({"type": "call.error", "callId": call_id, "error": err_msg})


def _schedule_copilot(call_id: str) -> None:
    """Coalesce rapid client turns: never stack N parallel/queued LLM calls behind one call lock."""
    _copilot_versions[call_id] = _copilot_versions.get(call_id, 0) + 1
    existing = _copilot_tasks.get(call_id)
    if existing and not existing.done():
        return
    _copilot_tasks[call_id] = asyncio.create_task(_copilot_loop(call_id))


async def _copilot_loop(call_id: str) -> None:
    try:
        while True:
            seen_ver = _copilot_versions.get(call_id, 0)
            await _run_call_copilot(call_id)
            if _copilot_versions.get(call_id, 0) == seen_ver:
                break
    except Exception as exc:
        print(f"[calls] background copilot failed for {call_id}: {exc}", flush=True)
    finally:
        _copilot_tasks.pop(call_id, None)


async def _safe_copilot(call_id: str) -> None:
    _schedule_copilot(call_id)


async def handle_webhook(payload: dict[str, Any]) -> dict[str, Any]:
    event = str(payload.get("event") or "").strip()
    call_id = str(payload.get("call_id") or "").strip()

    if event == "wa.boot":
        stale = [c for c in _calls.values() if c.get("status") in ("ringing", "active")]
        for rec in stale:
            rec["status"] = "ended"
            rec["endedAt"] = datetime.now(UTC).isoformat()
            rec["reason"] = "listener_restarted"
            _save_call(rec)
            await publish({"type": "call.ended", "callId": rec["callId"], "reason": "listener_restarted"})
        return {"status": "ok", "cleared": len(stale)}

    if event == "wa.status":
        await publish(
            {
                "type": "wa.status",
                "status": payload.get("status", "disconnected"),
                "phone": payload.get("phone", ""),
                "qrReady": bool(payload.get("qr_ready", False)),
            }
        )
        return {"status": "ok"}

    if not call_id:
        return {"status": "ignored"}

    phone = _digits(str(payload.get("from") or ""))

    if event == "call.incoming":
        cid, cname, known = await _resolve_client_by_phone(phone)
        rec = {
            "callId": call_id,
            "phoneNumber": phone,
            "clientId": cid,
            "clientName": cname,
            "knownClient": known,
            "status": "ringing",
            "mode": str(payload.get("mode") or "baileys_voip"),
            "startedAt": datetime.now(UTC).isoformat(),
            "endedAt": None,
            "reason": None,
            "muted": False,
            "committed": False,
            "utteranceSeq": 0,
            "transcripts": [],
            "linkedCommands": [],
            "warnings": [],
            "copilotNote": "",
            "stats": {},
        }
        _calls[call_id] = rec
        _save_call(rec)
        await publish({"type": "call.incoming", "call": rec})
        return {"status": "ok", "callId": call_id}

    rec = _calls.get(call_id)
    if rec is None:
        # Try loading from SQLite or bootstrap minimal record
        with _conn() as con:
            row = con.execute("SELECT * FROM call_sessions WHERE call_id=?", (call_id,)).fetchone()
            if row:
                rec = _row_to_dict(row)
                rec["utteranceSeq"] = len(rec["transcripts"])
                _calls[call_id] = rec
    if rec is None:
        cid, cname, known = await _resolve_client_by_phone(phone)
        rec = {
            "callId": call_id,
            "phoneNumber": phone,
            "clientId": cid,
            "clientName": cname,
            "knownClient": known,
            "status": "active",
            "mode": str(payload.get("mode") or "baileys_voip"),
            "startedAt": datetime.now(UTC).isoformat(),
            "endedAt": None,
            "reason": None,
            "muted": False,
            "committed": False,
            "utteranceSeq": 0,
            "transcripts": [],
            "linkedCommands": [],
            "warnings": [],
            "copilotNote": "",
            "stats": {},
        }
        _calls[call_id] = rec

    if event == "call.state":
        rec["status"] = str(payload.get("status") or "active")
        _save_call(rec)
        await publish({"type": "call.state", "callId": call_id, "status": rec["status"]})
        return {"status": "ok"}

    if event == "call.utterance":
        wav_b64 = str(payload.get("wav_base64") or "")
        duration_ms = int(payload.get("duration_ms") or 0)
        if not wav_b64:
            return {"status": "ignored", "reason": "empty_audio"}
        raw_wav = base64.b64decode(wav_b64)
        speaker = "manager" if str(payload.get("speaker") or "client").lower() == "manager" else "client"
        seq = int(rec.get("utteranceSeq", len(rec.get("transcripts") or []))) + 1
        rec["utteranceSeq"] = seq
        asyncio.create_task(_process_utterance(rec, call_id, seq, speaker, raw_wav, duration_ms))
        return {"status": "queued", "seq": seq}

    if event == "call.error":
        err = str(payload.get("error") or payload.get("message") or "Call error")
        await publish({"type": "call.error", "callId": call_id, "error": err})
        return {"status": "ok"}

    if event == "call.ended":
        rec["status"] = str(payload.get("status") or "ended")
        rec["endedAt"] = datetime.now(UTC).isoformat()
        rec["reason"] = str(payload.get("reason") or "ended")
        rec["stats"] = dict(payload.get("stats") or {})
        _save_call(rec)
        await publish({"type": "call.ended", "callId": call_id, "status": rec["status"], "reason": rec["reason"]})
        if rec.get("transcripts") and not rec.get("committed"):
            asyncio.create_task(_safe_copilot(call_id))
        return {"status": "ok"}

    return {"status": "ignored"}


def get_active_and_recent() -> dict[str, Any]:
    with _conn() as con:
        rows = con.execute("SELECT * FROM call_sessions ORDER BY started_at DESC LIMIT 30").fetchall()
        db_recent = [_row_to_dict(r) for r in rows]
    by_id = {r["callId"]: r for r in db_recent}
    for cid, rec in _calls.items():
        by_id[cid] = dict(rec)
    recent = sorted(by_id.values(), key=lambda x: str(x.get("startedAt") or ""), reverse=True)[:30]
    active = [c for c in recent if c.get("status") in ("ringing", "active")]
    return {"items": active, "recent": recent}


def get_call(call_id: str) -> dict[str, Any] | None:
    if call_id in _calls:
        return _calls[call_id]
    with _conn() as con:
        row = con.execute("SELECT * FROM call_sessions WHERE call_id=?", (call_id,)).fetchone()
        return _row_to_dict(row) if row else None


async def reset_test_state() -> dict[str, Any]:
    """Reset call history & ERP database back to seed while KEEPING WhatsApp session & 337 phone bindings intact."""
    active_ids = {cid for cid, rec in _calls.items() if rec.get("status") in ("ringing", "active")}
    try:
        wa_calls = await wa_get("/calls")
        for wc in wa_calls.get("items") or []:
            if wc.get("call_id"):
                active_ids.add(str(wc["call_id"]))
    except Exception:
        pass
    for cid in active_ids:
        try:
            await wa_post("/call/hangup", {"call_id": cid, "reason": "reset"}, timeout=4.0)
        except Exception:
            pass
    _calls.clear()
    _pending_sim_texts.clear()
    _copilot_locks.clear()
    _copilot_versions.clear()
    for task in list(_copilot_tasks.values()):
        task.cancel()
    _copilot_tasks.clear()
    with _conn() as con:
        con.execute("DELETE FROM call_sessions")
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(f"{settings.erp_api_url.rstrip('/')}/api/admin/reset")
        resp.raise_for_status()
        erp_res = resp.json()
    await publish({"type": "calls.reset"})
    return {"ok": True, "erp": erp_res, "preservedBindings": len(list_phone_bindings())}


async def confirm_call_order(call_id: str, order_id: str, actor_name: str = "Gestionnaire") -> dict[str, Any]:
    """Confirm a draft order linked to a call, updating the call record and broadcasting SSE."""
    rec = get_call(call_id)
    if not rec:
        raise LookupError(f"Appel introuvable : {call_id}")
    _calls[call_id] = rec
    erp = ErpClient("voice_agent", actor_name)
    r = await erp.post(f"/api/orders/{order_id}/confirm")
    cid = str(r.get("id") or order_id)
    cmd_obj = {
        "id": cid,
        "number": r.get("number") or cid,
        "status": r.get("status") or "confirmed",
        "deliveryDate": r.get("deliveryDate") or "",
        "totalHt": r.get("totalHt") or 0,
        "lineCount": len(r.get("lines") or []),
    }
    cmds = list(rec.get("linkedCommands") or [])
    if any(c.get("id") == cid for c in cmds):
        cmds = [cmd_obj if c.get("id") == cid else c for c in cmds]
    else:
        cmds.append(cmd_obj)
    warns = list(rec.get("warnings") or [])
    seen_warns = {(w.get("code"), w.get("message")) for w in warns}
    for w in r.get("warnings") or []:
        if isinstance(w, dict) and w.get("message"):
            key = (str(w.get("code", "warning")), str(w["message"]))
            if key not in seen_warns:
                seen_warns.add(key)
                warns.append({"code": key[0], "message": key[1]})
    rec["linkedCommands"] = cmds
    rec["warnings"] = warns
    rec["committed"] = True
    rec["copilotNote"] = f"Commande {cmd_obj['number']} confirmée dans l'ERP ({cmd_obj['totalHt']:.2f} € HT)."
    _save_call(rec)
    await publish(
        {
            "type": "call.copilot",
            "callId": call_id,
            "copilotNote": rec["copilotNote"],
            "linkedCommands": cmds,
            "warnings": warns,
        }
    )
    return rec


async def wa_get(path: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=8.0) as client:
        resp = await client.get(_wa_url(path))
        if resp.status_code >= 400:
            raise httpx.HTTPStatusError(resp.text[:250], request=resp.request, response=resp)
        return dict(resp.json())


async def wa_post(path: str, body: dict[str, Any] | None = None, timeout: float = 15.0) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(_wa_url(path), json=body or {})
        if resp.status_code >= 400:
            detail = resp.text[:300]
            try:
                j = resp.json()
                if isinstance(j, dict) and j.get("error"):
                    detail = str(j["error"])
            except Exception:
                pass
            raise RuntimeError(detail)
        return dict(resp.json())
