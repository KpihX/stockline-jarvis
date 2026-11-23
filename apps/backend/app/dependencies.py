"""Things routers get injected or share: who is calling, request-body helpers, query parsing."""

from __future__ import annotations

import re
from typing import Annotated, Any
from urllib.parse import unquote

from fastapi import Depends, Header

from app.core.activity import Ctx
from app.core.db import Doc
from app.core.errors import HttpError, validation_error
from app.schemas.base import Input
from app.schemas.views import ApiError

ACTORS = {"user", "ai_chat", "voice_agent", "system"}


def _bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    return parts[1].strip() if len(parts) == 2 and parts[0].lower() == "bearer" else None


def get_optional_account(authorization: Annotated[str | None, Header()] = None) -> Doc | None:
    from app.services.auth import verify_token

    tok = _bearer_token(authorization)
    return verify_token(tok) if tok else None


def require_account(authorization: Annotated[str | None, Header()] = None) -> Doc:
    acc = get_optional_account(authorization)
    if not acc:
        raise HttpError(401, "unauthorized", "Connexion requise.")
    return acc


def require_admin(account: Annotated[Doc, Depends(require_account)]) -> Doc:
    if account.get("role") != "admin":
        raise HttpError(403, "forbidden", "Accès réservé à l'administrateur unique.")
    return account


OptionalAccountDep = Annotated[Doc | None, Depends(get_optional_account)]
RequireAccountDep = Annotated[Doc, Depends(require_account)]
RequireAdminDep = Annotated[Doc, Depends(require_admin)]


def get_ctx(
    x_actor: Annotated[str | None, Header(description="user | ai_chat | voice_agent (default user)")] = None,
    x_actor_name: Annotated[str | None, Header(description="Display name of the actor (URI-encoded)")] = None,
) -> Ctx:
    """Who is calling: `x-actor` header + optional `x-actor-name`. Recorded on every ActivityEvent."""
    actor = x_actor if x_actor in ACTORS else "user"
    return Ctx(actor=actor, actor_name=unquote(x_actor_name) if x_actor_name else None)  # type: ignore[arg-type]


CtxDep = Annotated[Ctx, Depends(get_ctx)]
"""Use in a write route: `def create(..., ctx: CtxDep)`."""


def data(body: Input | None) -> dict[str, Any]:
    """The fields sent in an optional request body, as a dict (an empty body counts as {})."""
    return body.data() if body else {}


def iso_date_query(value: str | None) -> str | None:
    """Optional YYYY-MM-DD query param (400 otherwise)."""
    if value and not re.match(r"^\d{4}-\d{2}-\d{2}$", value):
        raise validation_error("body: format AAAA-MM-JJ attendu")
    return value or None


# Documented on every route: business errors share one JSON shape.
ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {"model": ApiError, "description": "Invalid request (validation_error, invalid_json, business rule)"},
    404: {"model": ApiError, "description": "Not found"},
    409: {"model": ApiError, "description": "Invalid state transition"},
}
