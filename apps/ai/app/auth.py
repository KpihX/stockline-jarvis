"""Bearer token resolution against the ERP `/api/auth/me` endpoint (cached 30 s per token hash).

Priority:
1. Valid Bearer token (header `Authorization: Bearer ...`, WS query `?token=`, or `StartMessage.token`)
   -> verified Caller (verified=True, exact account role & entityId).
2. No valid token -> if ALLOW_DECLARED_IDENTITY != "0", fall back to `Caller.declare(...)` (so CLI benches/scripts keep working).
3. Otherwise -> `UNKNOWN`.
"""

from __future__ import annotations

import hashlib
import time

import httpx

from app.config import env, settings
from app.policy import UNKNOWN, Caller

TOKEN_TTL_S = 30.0
_cache: dict[str, tuple[float, Caller]] = {}


def allow_declared() -> bool:
    return env("ALLOW_DECLARED_IDENTITY", "1") != "0"


def extract_bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    return parts[1].strip() if len(parts) == 2 and parts[0].lower() == "bearer" else None


async def verify_bearer(token: str | None) -> Caller | None:
    if not token:
        return None
    key = hashlib.sha256(token.encode("utf-8")).hexdigest()
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < TOKEN_TTL_S:
        return hit[1]
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            res = await client.get(f"{settings.erp_api_url}/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        if res.status_code != 200:
            return None
        caller = Caller.verified_account(res.json())
        _cache[key] = (time.monotonic(), caller)
        return caller
    except Exception:
        return None


async def resolve_caller(
    *,
    authorization: str | None = None,
    token: str | None = None,
    role: str | None = None,
    client_id: str | None = None,
    supplier_id: str | None = None,
    actor_name: str | None = None,
) -> Caller:
    raw = token or extract_bearer(authorization)
    if raw:
        verified = await verify_bearer(raw)
        if verified:
            return verified
    if allow_declared():
        return Caller.declare(role, client_id, actor_name, supplier_id=supplier_id)
    return UNKNOWN


def clear_cache() -> None:
    _cache.clear()
