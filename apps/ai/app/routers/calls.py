"""WhatsApp VoIP Call Desk & Baileys pairing routes (Manager & Admin only)."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import uuid
from typing import Any

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from app.auth import resolve_caller
from app.policy import Caller
from app.schemas import ErrorResponse
from app.services import calls as calls_svc

router = APIRouter(tags=["calls"])


class AcceptCallBody(BaseModel):
    sdp_offer: str | None = None
    sdpOffer: str | None = None


class ReasonBody(BaseModel):
    reason: str = "completed"


class MuteBody(BaseModel):
    muted: bool = True


class SimulateBody(BaseModel):
    phone: str = "0695497769"
    client_id: str | None = None
    clientId: str | None = None
    text: str = "Bonjour, c'est Le Refuge Payet, prépare-moi 200 kilos de frites surgelées pour le 1er décembre."


class InjectTextBody(BaseModel):
    text: str
    speaker: str = "client"


class BindClientBody(BaseModel):
    client_id: str | None = None
    clientId: str | None = None
    phone: str | None = None


class ConnectBody(BaseModel):
    reset: bool = False


async def _require_staff(request: Request) -> Caller | JSONResponse:
    caller = await resolve_caller(
        authorization=request.headers.get("authorization"),
        role=request.headers.get("x-caller-role"),
        client_id=request.headers.get("x-caller-client-id"),
        supplier_id=request.headers.get("x-caller-supplier-id"),
        actor_name=request.headers.get("x-actor-name"),
    )
    if caller.role not in ("manager", "admin"):
        return JSONResponse(
            ErrorResponse.of("forbidden", "Accès réservé aux commerciaux et à l'administrateur."),
            status_code=403,
        )
    return caller


# ── Internal webhooks from apps/wa ──


@router.post("/webhooks/call")
async def webhook_call(payload: dict[str, Any]) -> dict[str, Any]:
    return await calls_svc.handle_webhook(payload)


@router.post("/webhooks/whatsapp")
async def webhook_whatsapp(payload: dict[str, Any]) -> dict[str, Any]:
    await calls_svc.publish({"type": "wa.message", "signal": payload})
    return {"status": "ok"}


# ── WhatsApp Pairing / QR Code (Manager & Admin) ──


@router.get("/wa/status")
async def wa_status(request: Request):
    guard = await _require_staff(request)
    if isinstance(guard, JSONResponse):
        return guard
    try:
        data = await calls_svc.wa_get("/status")
        return {
            "status": data.get("status", "disconnected"),
            "phone": data.get("phone", ""),
            "qrReady": bool(data.get("qr_ready", False)),
        }
    except Exception:
        return {"status": "unavailable", "phone": "", "qrReady": False}


@router.get("/wa/qr")
async def wa_qr(request: Request):
    guard = await _require_staff(request)
    if isinstance(guard, JSONResponse):
        return guard
    try:
        return await calls_svc.wa_get("/qr")
    except httpx.HTTPStatusError as exc:
        return JSONResponse(ErrorResponse.of("no_qr", "QR Code indisponible pour le moment."), status_code=exc.response.status_code)
    except Exception as exc:
        return JSONResponse(ErrorResponse.of("wa_unavailable", str(exc)), status_code=502)


@router.post("/wa/connect")
async def wa_connect(request: Request, body: ConnectBody | None = None):
    guard = await _require_staff(request)
    if isinstance(guard, JSONResponse):
        return guard
    try:
        return await calls_svc.wa_post("/connect", {"reset": bool(body.reset if body else False)})
    except Exception as exc:
        return JSONResponse(ErrorResponse.of("wa_unavailable", str(exc)), status_code=502)


@router.post("/wa/disconnect")
async def wa_disconnect(request: Request):
    guard = await _require_staff(request)
    if isinstance(guard, JSONResponse):
        return guard
    try:
        return await calls_svc.wa_post("/disconnect")
    except Exception as exc:
        return JSONResponse(ErrorResponse.of("wa_unavailable", str(exc)), status_code=502)


# ── Call Desk endpoints (Manager & Admin) ──


@router.get("/calls/config")
async def calls_config(request: Request):
    guard = await _require_staff(request)
    if isinstance(guard, JSONResponse):
        return guard
    ice_raw = os.environ.get("ICE_SERVERS") or "stun:stun.l.google.com:19302"
    ice_urls = [u.strip() for u in ice_raw.split(",") if u.strip()]
    return {
        "provider": "baileys_voip",
        "sampleRate": 16000,
        "webrtcRate": 48000,
        "iceServers": [{"urls": u} for u in ice_urls],
        "bindings": calls_svc.list_phone_bindings(),
    }


@router.get("/calls/active")
async def calls_active(request: Request):
    guard = await _require_staff(request)
    if isinstance(guard, JSONResponse):
        return guard
    return calls_svc.get_active_and_recent()


@router.post("/calls/reset")
async def calls_reset(request: Request):
    """Wipe test calls + reset ERP to seed while preserving WhatsApp QR pairing and phone bindings."""
    guard = await _require_staff(request)
    if isinstance(guard, JSONResponse):
        return guard
    return await calls_svc.reset_test_state()


@router.get("/calls/stream")
async def calls_stream(request: Request, token: str | None = None):
    # EventSource cannot set Authorization header cleanly, so accept ?token= fallback too
    caller = await resolve_caller(
        authorization=request.headers.get("authorization") or (f"Bearer {token}" if token else None),
        role=request.headers.get("x-caller-role"),
    )
    if caller.role not in ("manager", "admin"):
        return JSONResponse(ErrorResponse.of("forbidden", "Accès réservé."), status_code=403)

    async def stream():
        q = calls_svc.subscribe()
        try:
            yield f"data: {json.dumps({'type': 'stream.connected'})}\n\n"
            while True:
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
                    continue
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
        finally:
            calls_svc.unsubscribe(q)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@router.get("/calls/{call_id}")
async def call_detail(call_id: str, request: Request):
    guard = await _require_staff(request)
    if isinstance(guard, JSONResponse):
        return guard
    rec = calls_svc.get_call(call_id)
    if not rec:
        return JSONResponse(ErrorResponse.of("not_found", f"Appel introuvable : {call_id}"), status_code=404)
    return rec


@router.post("/calls/bind-phone")
async def bind_phone(body: BindClientBody, request: Request):
    guard = await _require_staff(request)
    if isinstance(guard, JSONResponse):
        return guard
    cid = body.client_id or body.clientId or ""
    if not body.phone or not cid:
        return JSONResponse(ErrorResponse.of("bad_request", "phone et clientId requis."), status_code=400)
    try:
        return await calls_svc.bind_phone_to_client(body.phone, cid)
    except Exception as exc:
        return JSONResponse(ErrorResponse.of("bad_request", str(exc)), status_code=400)


@router.post("/calls/{call_id}/bind-client")
async def bind_call_client(call_id: str, body: BindClientBody, request: Request):
    guard = await _require_staff(request)
    if isinstance(guard, JSONResponse):
        return guard
    rec = calls_svc.get_call(call_id)
    if not rec:
        return JSONResponse(ErrorResponse.of("not_found", f"Appel introuvable : {call_id}"), status_code=404)
    cid = body.client_id or body.clientId or ""
    if not cid:
        return JSONResponse(ErrorResponse.of("bad_request", "clientId requis."), status_code=400)
    res = await calls_svc.bind_phone_to_client(rec["phoneNumber"], cid)
    await calls_svc.publish({"type": "call.state", "callId": call_id, "status": rec["status"], "client": res})
    return res


@router.post("/calls/{call_id}/accept")
async def accept_call(call_id: str, body: AcceptCallBody, request: Request):
    guard = await _require_staff(request)
    if isinstance(guard, JSONResponse):
        return guard
    sdp = body.sdp_offer or body.sdpOffer or ""
    if not sdp:
        return JSONResponse(ErrorResponse.of("bad_request", "sdpOffer requis."), status_code=400)
    try:
        data = await calls_svc.wa_post("/call/accept", {"call_id": call_id, "sdp_offer": sdp}, timeout=20.0)
        rec = calls_svc.get_call(call_id)
        if rec:
            rec["status"] = "active"
            calls_svc._save_call(rec)
        return {
            "callId": data.get("call_id", call_id),
            "status": data.get("status", "active"),
            "sdpAnswer": data.get("sdp_answer", ""),
            "mode": data.get("mode", "baileys_voip"),
        }
    except Exception as exc:
        msg = str(exc)
        if "not found" in msg.lower():
            rec = calls_svc.get_call(call_id)
            if rec:
                rec["status"] = "ended"
                rec["reason"] = "expired"
                calls_svc._save_call(rec)
            return JSONResponse(ErrorResponse.of("conflict", f"Appel expiré : {msg}"), status_code=409)
        return JSONResponse(ErrorResponse.of("wa_error", f"Échec acceptation WebRTC : {msg}"), status_code=502)


@router.post("/calls/{call_id}/reject")
async def reject_call(call_id: str, request: Request, body: ReasonBody | None = None):
    guard = await _require_staff(request)
    if isinstance(guard, JSONResponse):
        return guard
    try:
        data = await calls_svc.wa_post("/call/reject", {"call_id": call_id, "reason": body.reason if body else "declined"})
        return data
    except Exception as exc:
        return JSONResponse(ErrorResponse.of("wa_error", str(exc)), status_code=502)


@router.post("/calls/{call_id}/hangup")
async def hangup_call(call_id: str, request: Request, body: ReasonBody | None = None):
    guard = await _require_staff(request)
    if isinstance(guard, JSONResponse):
        return guard
    try:
        data = await calls_svc.wa_post("/call/hangup", {"call_id": call_id, "reason": body.reason if body else "completed"})
        return data
    except Exception as exc:
        return JSONResponse(ErrorResponse.of("wa_error", str(exc)), status_code=502)


@router.post("/calls/{call_id}/mute")
async def mute_call(call_id: str, body: MuteBody, request: Request):
    guard = await _require_staff(request)
    if isinstance(guard, JSONResponse):
        return guard
    try:
        return await calls_svc.wa_post("/call/mute", {"call_id": call_id, "muted": body.muted}, timeout=6.0)
    except Exception as exc:
        return JSONResponse(ErrorResponse.of("wa_error", str(exc)), status_code=502)


@router.post("/calls/{call_id}/commit")
async def commit_call(call_id: str, request: Request):
    guard = await _require_staff(request)
    if isinstance(guard, JSONResponse):
        return guard
    rec = await calls_svc._run_call_copilot(call_id)
    if rec is None:
        return JSONResponse(ErrorResponse.of("bad_request", "Aucune parole transcrite à analyser."), status_code=400)
    return rec


@router.post("/calls/{call_id}/orders/{order_id}/confirm")
async def confirm_call_order(call_id: str, order_id: str, request: Request):
    guard = await _require_staff(request)
    if isinstance(guard, JSONResponse):
        return guard
    try:
        return await calls_svc.confirm_call_order(call_id, order_id, guard.erp_name)
    except LookupError as exc:
        return JSONResponse(ErrorResponse.of("not_found", str(exc)), status_code=404)
    except Exception as exc:
        return JSONResponse(ErrorResponse.of("erp_error", str(exc)), status_code=400)


@router.post("/calls/simulate")
async def simulate_call(body: SimulateBody, request: Request):
    guard = await _require_staff(request)
    if isinstance(guard, JSONResponse):
        return guard
    phone = calls_svc._digits(body.phone) or "0695497769"
    cid = body.client_id or body.clientId
    if cid:
        await calls_svc.bind_phone_to_client(phone, cid)
    call_id = f"SIM-{uuid.uuid4().hex[:10].upper()}"
    text = body.text.strip()
    wav_b64 = ""
    if text:
        calls_svc._pending_sim_texts.setdefault(call_id, []).append(text)
        wav_bytes = await calls_svc.synthesize_wav_16k(text)
        wav_b64 = base64.b64encode(wav_bytes).decode("ascii")
    try:
        data = await calls_svc.wa_post("/call/simulate", {"from": phone, "wav_base64": wav_b64, "call_id": call_id})
        return {"callId": data.get("call_id", call_id), "from": data.get("from", phone), "status": data.get("status", "ringing")}
    except Exception as exc:
        return JSONResponse(ErrorResponse.of("wa_unavailable", f"Simulation échouée : {exc}"), status_code=502)


@router.post("/calls/{call_id}/inject-text")
async def inject_text(call_id: str, body: InjectTextBody, request: Request):
    guard = await _require_staff(request)
    if isinstance(guard, JSONResponse):
        return guard
    text = body.text.strip()
    if not text:
        return JSONResponse(ErrorResponse.of("bad_request", "Texte requis."), status_code=400)
    speaker = "manager" if body.speaker.lower() == "manager" else "client"
    if speaker == "client":
        calls_svc._pending_sim_texts.setdefault(call_id, []).append(text)
    wav_bytes = await calls_svc.synthesize_wav_16k(text)
    wav_b64 = base64.b64encode(wav_bytes).decode("ascii")
    try:
        return await calls_svc.wa_post("/call/inject-audio", {"call_id": call_id, "wav_base64": wav_b64, "speaker": speaker})
    except Exception as exc:
        return JSONResponse(ErrorResponse.of("wa_unavailable", str(exc)), status_code=502)
