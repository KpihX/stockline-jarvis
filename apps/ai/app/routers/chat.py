"""POST /chat: the agent, streamed as Server-Sent Events."""

from fastapi import APIRouter, Request

from app.agent import run_agent, sanitize_history
from app.clients import get_llm_client
from app.schemas import ChatRequest
from app.tools import all_tools

from .command import caller_of_request
from .sse import sse_doc, sse_response

router = APIRouter(tags=["agent"])


@router.post("/chat", responses=sse_doc("ChatStreamEvent"))
async def chat(body: ChatRequest, request: Request):
    """ChatRequest → text/event-stream of ChatStreamEvent. The caller's DECLARED identity (role, clientId, actorName in the body, or the
    x-caller-role / x-caller-client-id / x-actor-name headers; default unknown) decides what the agent may do (app/policy.py)."""
    # The harness owns the system prompt; a client-rebuilt history with a broken tool pairing must not 400 the provider.
    messages = sanitize_history(body.messages)
    caller = caller_of_request(request.headers, body.role, body.client_id, body.actor_name)
    return sse_response(
        run_agent(messages, llm=get_llm_client(), tools=all_tools(), mode=body.mode or "chat", actor_name=body.actor_name, caller=caller)
    )
