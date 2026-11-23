"""Sessions REST API: CRUD + accent-folded search over the shared SQLite session store."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.auth import resolve_caller
from app.policy import Caller
from app.schemas import ErrorResponse
from app.services import sessions, suggestions

from .command import header_text

router = APIRouter(tags=["sessions"])


class SessionCreateBody(BaseModel):
    title: str | None = None
    surface: Literal["chat", "voice"] | None = "chat"


class SessionRenameBody(BaseModel):
    title: str


async def _caller(request: Request) -> Caller:
    return await resolve_caller(
        authorization=request.headers.get("authorization"),
        role=request.headers.get("x-caller-role"),
        client_id=request.headers.get("x-caller-client-id"),
        supplier_id=request.headers.get("x-caller-supplier-id"),
        actor_name=header_text(request.headers.get("x-actor-name")),
    )


@router.get("/suggestions")
async def get_suggestions(request: Request, seed: int = 0, live: int = 1):
    caller = await _caller(request)
    return await suggestions.build_suggestions(caller, seed=seed, use_llm=bool(live))


@router.get("/sessions")
async def list_sessions(
    request: Request,
    q: str = "",
    role: str | None = None,
    client_id: str | None = Query(None, alias="clientId"),
    surface: Literal["chat", "voice"] | None = None,
    limit: int = 50,
    offset: int = 0,
):
    caller = await _caller(request)
    return sessions.list_sessions(q=q, caller=caller, role=role, client_id=client_id, surface=surface, limit=limit, offset=offset)


@router.post("/sessions", status_code=201)
async def create_session(body: SessionCreateBody, request: Request):
    caller = await _caller(request)
    return sessions.create_session(title=body.title, surface=body.surface, caller=caller)


@router.get("/sessions/{sid}", responses={404: {"model": ErrorResponse}})
async def get_session(sid: str, request: Request):
    caller = await _caller(request)
    d = sessions.detail(sid, caller=caller)
    if d is None:
        return JSONResponse(ErrorResponse.of("not_found", f"Session introuvable : {sid}"), status_code=404)
    return d


@router.patch("/sessions/{sid}", responses={404: {"model": ErrorResponse}})
async def rename_session(sid: str, body: SessionRenameBody, request: Request):
    caller = await _caller(request)
    d = sessions.rename(sid, body.title, caller=caller)
    if d is None:
        return JSONResponse(ErrorResponse.of("not_found", f"Session introuvable : {sid}"), status_code=404)
    return d


@router.post("/sessions/{sid}/reopen", responses={404: {"model": ErrorResponse}})
async def reopen_session(sid: str, request: Request):
    caller = await _caller(request)
    d = sessions.reopen(sid, caller=caller)
    if d is None:
        return JSONResponse(ErrorResponse.of("not_found", f"Session introuvable : {sid}"), status_code=404)
    return d


@router.delete("/sessions/{sid}", status_code=204, responses={404: {"model": ErrorResponse}})
async def delete_session(sid: str, request: Request):
    caller = await _caller(request)
    if not sessions.remove(sid, caller=caller):
        return JSONResponse(ErrorResponse.of("not_found", f"Session introuvable : {sid}"), status_code=404)
