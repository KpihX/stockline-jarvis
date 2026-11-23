"""Auth routes: login, logout, current profile, and public demo quick-login accounts."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.dependencies import RequireAccountDep
from app.services import auth

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginBody(BaseModel):
    username: str
    password: str


@router.post("/login")
def login(body: LoginBody, request: Request) -> dict[str, Any]:
    client_key = request.client.host if request.client else "local"
    return auth.login(body.username, body.password, client_key=client_key)


@router.post("/logout")
def logout() -> dict[str, bool]:
    # Stateless HMAC token: client clears localStorage; endpoint stays explicit for auditing/symmetry.
    return {"ok": True}


@router.get("/me")
def me(account: RequireAccountDep) -> dict[str, Any]:
    return auth.public_account(account)


@router.get("/demo-accounts")
def demo_accounts() -> list[dict[str, Any]]:
    return auth.demo_accounts_list()
