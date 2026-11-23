"""Authentication & user accounts (client, supplier, manager, exactly ONE admin).

- Passwords: stdlib `hashlib.scrypt` with random 16-byte salt (`scrypt$<salt>$<hex>`). Never logged or returned.
- Tokens: stdlib HMAC-SHA256 signed base64url JSON payload (`exp`, `sub`, `role`, `entityType`, `entityId`, `displayName`),
  12h TTL. Secret read from `AUTH_SECRET` env or auto-generated once and stored in SQLite `meta['auth_secret']`.
- Single-admin invariant: there is always EXACTLY ONE admin account. Creating/promoting a second admin or
  deleting/deactivating/demoting the sole admin fails with HTTP 409.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import UTC, datetime
from typing import Any

from app import crud
from app.core.activity import Ctx, log_event
from app.core.db import Doc, conn, transactional
from app.core.errors import HttpError, bad_request, conflict, not_found

ROLES = ("client", "supplier", "manager", "admin")
TOKEN_TTL_S = 12 * 3600
LOGIN_WINDOW_S = 60.0
LOGIN_MAX_ATTEMPTS = 25

_login_attempts: dict[str, list[float]] = {}
_secret_cache: bytes | None = None


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def get_secret() -> bytes:
    """HMAC signing key: `AUTH_SECRET` env if set, else generated once and persisted in SQLite `meta`."""
    global _secret_cache
    env_sec = os.environ.get("AUTH_SECRET", "").strip()
    if env_sec:
        return env_sec.encode("utf-8")
    if _secret_cache is not None:
        return _secret_cache
    row = conn.execute("SELECT value FROM meta WHERE key = 'auth_secret'").fetchone()
    if row and row[0]:
        _secret_cache = row[0].encode("utf-8")
        return _secret_cache
    gen = secrets.token_urlsafe(48)
    conn.execute(
        "INSERT INTO meta (key, value) VALUES ('auth_secret', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (gen,),
    )
    _secret_cache = gen.encode("utf-8")
    return _secret_cache


def reset_secret_cache() -> None:
    global _secret_cache
    _secret_cache = None


def hash_password(password: str) -> str:
    if len(password) < 4:
        raise bad_request("weak_password", "Le mot de passe doit contenir au moins 4 caractères.")
    salt = secrets.token_hex(16)
    dk = hashlib.scrypt(password.encode("utf-8"), salt=salt.encode("ascii"), n=16384, r=8, p=1)
    return f"scrypt${salt}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt, digest = stored.split("$", 2)
        if scheme != "scrypt":
            return False
        dk = hashlib.scrypt(password.encode("utf-8"), salt=salt.encode("ascii"), n=16384, r=8, p=1)
        return hmac.compare_digest(dk.hex(), digest)
    except Exception:
        return False


def _b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64u(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def issue_token(account: Doc) -> tuple[str, str]:
    exp_ts = int(time.time()) + TOKEN_TTL_S
    payload = {
        "sub": account["id"],
        "username": account["username"],
        "displayName": account["displayName"],
        "role": account["role"],
        "entityType": account.get("entityType"),
        "entityId": account.get("entityId"),
        "exp": exp_ts,
    }
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    body = _b64u(raw)
    sig = _b64u(hmac.new(get_secret(), body.encode("ascii"), hashlib.sha256).digest())
    exp_iso = datetime.fromtimestamp(exp_ts, UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    return f"{body}.{sig}", exp_iso


def verify_token(token: str) -> Doc | None:
    if not token or "." not in token:
        return None
    try:
        body, sig = token.split(".", 1)
        expected = _b64u(hmac.new(get_secret(), body.encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected):
            return None
        payload = json.loads(_unb64u(body))
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        acc = crud.accounts.get(payload.get("sub", ""))
        if not acc or not acc.get("active", True):
            return None
        return acc
    except Exception:
        return None


def public_account(acc: Doc) -> Doc:
    """Strip passwordHash before returning any account to a caller."""
    return {k: v for k, v in acc.items() if k != "passwordHash"}


def _admin_accounts() -> list[Doc]:
    return [a for a in crud.accounts.all() if a.get("role") == "admin"]


def _check_rate_limit(key: str) -> None:
    now = time.monotonic()
    hits = [t for t in _login_attempts.get(key, []) if now - t < LOGIN_WINDOW_S]
    if len(hits) >= LOGIN_MAX_ATTEMPTS:
        raise HttpError(429, "too_many_attempts", "Trop de tentatives de connexion : réessayez dans une minute.")
    hits.append(now)
    _login_attempts[key] = hits


def _validate_entity(role: str, entity_type: str | None, entity_id: str | None) -> tuple[str | None, str | None, str | None]:
    if role == "client":
        if not entity_id:
            raise bad_request("missing_entity", "Un compte client doit être rattaché à un client (cli_…).")
        client = crud.clients.require(entity_id)
        return "client", entity_id, client["name"]
    if role == "supplier":
        if not entity_id:
            raise bad_request("missing_entity", "Un compte fournisseur doit être rattaché à un fournisseur (sup_…).")
        sup = crud.suppliers.require(entity_id)
        return "supplier", entity_id, sup["name"]
    if role == "manager":
        return (entity_type or "salesRep"), entity_id, None
    return None, None, None


def login(username: str, password: str, *, client_key: str = "local") -> Doc:
    uname = (username or "").strip().lower()
    _check_rate_limit(f"{client_key}:{uname}")
    acc = next((a for a in crud.accounts.all() if a["username"].lower() == uname), None)
    if not acc or not verify_password(password, acc.get("passwordHash", "")):
        raise HttpError(401, "invalid_credentials", "Identifiant ou mot de passe incorrect.")
    if not acc.get("active", True):
        raise HttpError(403, "account_disabled", "Ce compte est désactivé. Contactez l'administrateur.")
    updated = {**acc, "lastLoginAt": _now_iso()}
    crud.accounts.table.put(updated)
    token, expires_at = issue_token(updated)
    return {"token": token, "expiresAt": expires_at, "account": public_account(updated)}


def list_accounts() -> list[Doc]:
    return [public_account(a) for a in crud.accounts.all()]


def demo_accounts_list() -> list[Doc]:
    """Public demo switcher list: ONLY accounts explicitly flagged `demoPassword` (never real secrets)."""
    out = []
    for a in crud.accounts.all():
        if not a.get("active", True) or not a.get("demoHint"):
            continue
        out.append({
            "id": a["id"],
            "username": a["username"],
            "displayName": a["displayName"],
            "role": a["role"],
            "entityType": a.get("entityType"),
            "entityId": a.get("entityId"),
            "entityLabel": a.get("entityLabel"),
            "demoPassword": a.get("demoHint"),
        })
    return out


@transactional
def create_account(data: Doc, ctx: Ctx) -> Doc:
    role = data.get("role")
    if role not in ROLES:
        raise bad_request("invalid_role", f"Rôle invalide : {role}")
    if role == "admin" and _admin_accounts():
        raise conflict("single_admin", "Un administrateur unique existe déjà : impossible d'en créer un second.")
    username = (data.get("username") or "").strip().lower()
    if not username or len(username) < 2:
        raise bad_request("invalid_username", "Nom d'utilisateur requis (2 caractères min.).")
    if any(a["username"].lower() == username for a in crud.accounts.all()):
        raise conflict("username_taken", f"L'identifiant « {username} » est déjà utilisé.")
    etype, eid, elabel = _validate_entity(role, data.get("entityType"), data.get("entityId"))
    acc_id = crud.accounts.next_id()
    acc: Doc = {
        "id": acc_id,
        "username": username,
        "displayName": (data.get("displayName") or elabel or username).strip(),
        "role": role,
        "entityType": etype,
        "entityId": eid,
        "entityLabel": elabel or data.get("entityLabel"),
        "passwordHash": hash_password(data.get("password") or ""),
        "active": bool(data.get("active", True)),
        "createdAt": _now_iso(),
        "lastLoginAt": None,
    }
    crud.accounts.table.put(acc)
    log_event(ctx, "account.created", "account", acc_id, f"Compte {username} ({role}) créé")
    return public_account(acc)


@transactional
def update_account(account_id: str, data: Doc, ctx: Ctx) -> Doc:
    cur = crud.accounts.require(account_id)
    new_role = data.get("role", cur["role"])
    if new_role not in ROLES:
        raise bad_request("invalid_role", f"Rôle invalide : {new_role}")
    if cur["role"] == "admin":
        if new_role != "admin":
            raise conflict("single_admin", "Impossible de rétrograder l'administrateur unique.")
        if data.get("active") is False:
            raise conflict("single_admin", "Impossible de désactiver l'administrateur unique.")
    elif new_role == "admin":
        raise conflict("single_admin", "Un administrateur unique existe déjà : promotion refusée.")

    etype, eid, elabel = cur.get("entityType"), cur.get("entityId"), cur.get("entityLabel")
    if "role" in data or "entityId" in data or "entityType" in data:
        etype, eid, elabel = _validate_entity(
            new_role,
            data.get("entityType", cur.get("entityType")),
            data.get("entityId", cur.get("entityId")),
        )
    updated: Doc = {
        **cur,
        "displayName": (data.get("displayName") or cur["displayName"]).strip(),
        "role": new_role,
        "entityType": etype,
        "entityId": eid,
        "entityLabel": elabel or data.get("entityLabel") or cur.get("entityLabel"),
        "active": bool(data.get("active", cur.get("active", True))),
    }
    crud.accounts.table.put(updated)
    log_event(ctx, "account.updated", "account", account_id, f"Compte {cur['username']} mis à jour")
    return public_account(updated)


@transactional
def reset_password(account_id: str, new_password: str, ctx: Ctx) -> Doc:
    cur = crud.accounts.require(account_id)
    updated = {**cur, "passwordHash": hash_password(new_password)}
    updated.pop("demoHint", None)
    crud.accounts.table.put(updated)
    log_event(ctx, "account.password_reset", "account", account_id, f"Mot de passe réinitialisé pour {cur['username']}")
    return public_account(updated)


@transactional
def delete_account(account_id: str, ctx: Ctx) -> None:
    cur = crud.accounts.require(account_id)
    if cur["role"] == "admin":
        raise conflict("single_admin", "Impossible de supprimer l'administrateur unique.")
    crud.accounts.table.remove(account_id)
    log_event(ctx, "account.deleted", "account", account_id, f"Compte {cur['username']} supprimé")


def ensure_accounts_seeded(*, force_reset: bool = False) -> None:
    """Seed deterministic demo accounts (1 admin, managers from clients.salesRep, demo clients & suppliers)."""
    if not force_reset and crud.accounts.rows:
        return
    admin_env = os.environ.get("ADMIN_PASSWORD", "").strip()
    admin_pw = admin_env or "demo-admin"
    now = _now_iso()
    clients = crud.clients.rows
    suppliers = crud.suppliers.rows

    specs: list[dict[str, Any]] = [
        ("acc_admin", "admin", "Direction Alpes", "admin", None, None, "Administrateur unique", admin_pw, None if admin_env else "demo-admin"),
        ("acc_mgr_thibault", "thibault", "Thibault Gros", "manager", "salesRep", "Thibault Gros", "Commercial · 25 clients", "demo-thibault", "demo-thibault"),
        ("acc_mgr_emilie", "emilie", "Émilie Brun", "manager", "salesRep", "Émilie Brun", "Commerciale · 36 clients", "demo-emilie", "demo-emilie"),
    ]
    for acc_id, uname, cid, pw in [
        ("acc_cli_payet", "payet", "cli_0082", "demo-payet"),
        ("acc_cli_leila", "leila", "cli_0033", "demo-leila"),
        ("acc_cli_igloo", "igloo", "cli_0014", "demo-igloo"),
    ]:
        if cid in clients:
            specs.append((acc_id, uname, clients[cid]["name"], "client", "client", cid, clients[cid]["name"], pw, pw))
    for acc_id, uname, sid, pw in [
        ("acc_sup_chambaran", "chambaran", "sup_0007", "demo-chambaran"),
        ("acc_sup_perrier", "perrier", "sup_0001", "demo-perrier"),
    ]:
        if sid in suppliers:
            specs.append((acc_id, uname, suppliers[sid]["name"], "supplier", "supplier", sid, suppliers[sid]["name"], pw, pw))

    rows: list[Doc] = []
    for acc_id, uname, dname, role, etype, eid, elabel, pw, hint in specs:
        doc: Doc = {
            "id": acc_id,
            "username": uname,
            "displayName": dname,
            "role": role,
            "entityType": etype,
            "entityId": eid,
            "entityLabel": elabel,
            "passwordHash": hash_password(pw),
            "active": True,
            "createdAt": now,
            "lastLoginAt": None,
        }
        if hint:
            doc["demoHint"] = hint
        rows.append(doc)
    crud.accounts.table.replace_all(rows)
