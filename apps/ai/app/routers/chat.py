"""POST /chat: the agent, streamed as Server-Sent Events."""

from fastapi import APIRouter, Request

from app.auth import resolve_caller
from app.agent import run_agent, sanitize_history
from app.clients import get_llm_client
from app.schemas import ChatRequest
from app.services import sessions
from app.tools import all_tools

from .command import header_text
from .sse import sse_doc, sse_response

router = APIRouter(tags=["agent"])


@router.post("/chat", responses=sse_doc("ChatStreamEvent"))
async def chat(body: ChatRequest, request: Request):
    """ChatRequest → text/event-stream of ChatStreamEvent. When sessionId is provided, uses the server-owned SQLite store shared with WS /voice."""
    messages = sanitize_history(body.messages)
    caller = await resolve_caller(
        authorization=request.headers.get("authorization"),
        role=body.role or request.headers.get("x-caller-role"),
        client_id=body.client_id or request.headers.get("x-caller-client-id"),
        supplier_id=body.supplier_id or request.headers.get("x-caller-supplier-id"),
        actor_name=body.actor_name or header_text(request.headers.get("x-actor-name")),
    )
    if body.session_id:
        conv = sessions.get(
            body.session_id,
            caller=caller,
            actor_name=caller.actor_name or body.actor_name,
            surface="chat",
        )
        return sse_response(
            sessions.chat_turn(
                conv,  # type: ignore[arg-type]
                messages=messages,
                caller=caller,
                actor_name=caller.actor_name or body.actor_name,
                mode=body.mode or "chat",
                current_path=body.current_path,
            )
        )
    return sse_response(
        run_agent(messages, llm=get_llm_client(), tools=all_tools(), mode=body.mode or "chat", actor_name=caller.actor_name or body.actor_name, caller=caller)
    )
