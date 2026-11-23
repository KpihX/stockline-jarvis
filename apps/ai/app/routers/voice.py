"""WS /voice: push-to-talk voice sessions (protocol: app/schemas/voice.py, logic: app/services/voice_session.py).
WS /voice/command: one voice command with live transcription (app/services/command.py, serve_command_ws)."""

from fastapi import APIRouter, WebSocket

from app.auth import resolve_caller
from app.policy import Caller
from app.services.command import serve_command_ws
from app.services.voice_session import VoiceConnection

router = APIRouter()


@router.websocket("/voice")
async def voice(ws: WebSocket):
    await VoiceConnection(ws).serve()


@router.websocket("/voice/command")
async def voice_command(
    ws: WebSocket,
    speak: str | None = None,
    token: str | None = None,
    role: str | None = None,
    clientId: str | None = None,
    supplierId: str | None = None,
    actorName: str | None = None,
):
    """Identity resolved via Bearer token (`token` query / Authorization header) or declared fallback when allowed."""
    caller = await resolve_caller(
        authorization=ws.headers.get("authorization"),
        token=token,
        role=role,
        client_id=clientId,
        supplier_id=supplierId,
        actor_name=actorName,
    )
    await serve_command_ws(ws, speak=speak in ("1", "true"), caller=caller)
