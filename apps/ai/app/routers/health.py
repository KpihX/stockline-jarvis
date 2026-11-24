"""GET /health and GET /tools."""

from fastapi import APIRouter

from app.clients import get_llm_client, get_stt_client, get_tts_client
from app.config import settings
from app.schemas import HealthResponse, LLMInfo, ProviderInfo, ToolInfo
from app.tools import all_tools

router = APIRouter(tags=["service"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    llm = get_llm_client()
    return HealthResponse(
        ok=True,
        llm=LLMInfo(provider=llm.provider, model=llm.model),
        stt=ProviderInfo(provider=get_stt_client().name),
        tts=ProviderInfo(provider=get_tts_client().name),
        erp_api_url=settings.erp_api_url,
    )


@router.get("/tools", response_model=list[ToolInfo])
async def tools() -> list[ToolInfo]:
    """The tools the agent exposes to the model (name, description, JSON schema)."""
    return [t.info for t in all_tools()]


@router.get("/jev/stats")
async def jev_stats() -> dict:
    """Live measured Jev System One telemetry (p50/p90/count/errors per decision primitive)."""
    from app.clients import get_jev_client
    from app.services import jev_router

    jev = get_jev_client()
    return {
        "enabled": jev is not None,
        "model": settings.jev.model if jev is not None else None,
        "timeoutMs": int(jev_router.JEV_TIMEOUT_S * 1000),
        "stats": jev_router.latency_stats(),
    }
