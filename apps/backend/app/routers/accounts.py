"""Admin-only account management CRUD (/api/accounts). Enforces the single-admin invariant."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel

from app.dependencies import CtxDep, RequireAdminDep
from app.services import auth

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


class AccountCreate(BaseModel):
    username: str
    displayName: str | None = None
    role: Literal["client", "supplier", "manager", "admin"]
    entityType: str | None = None
    entityId: str | None = None
    password: str
    active: bool = True


class AccountUpdate(BaseModel):
    displayName: str | None = None
    role: Literal["client", "supplier", "manager", "admin"] | None = None
    entityType: str | None = None
    entityId: str | None = None
    active: bool | None = None


class PasswordReset(BaseModel):
    password: str


@router.get("")
def list_accounts(_: RequireAdminDep) -> list[dict[str, Any]]:
    return auth.list_accounts()


@router.post("", status_code=201)
def create_account(body: AccountCreate, ctx: CtxDep, _: RequireAdminDep) -> dict[str, Any]:
    return auth.create_account(body.model_dump(), ctx)


@router.patch("/{account_id}")
def update_account(account_id: str, body: AccountUpdate, ctx: CtxDep, _: RequireAdminDep) -> dict[str, Any]:
    return auth.update_account(account_id, body.model_dump(exclude_unset=True), ctx)


@router.post("/{account_id}/reset-password")
def reset_password(account_id: str, body: PasswordReset, ctx: CtxDep, _: RequireAdminDep) -> dict[str, Any]:
    return auth.reset_password(account_id, body.password, ctx)


@router.delete("/{account_id}", status_code=204)
def delete_account(account_id: str, ctx: CtxDep, _: RequireAdminDep) -> None:
    auth.delete_account(account_id, ctx)
