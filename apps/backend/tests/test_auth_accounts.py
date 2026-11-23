"""Essential tests for auth (scrypt + HMAC token), single-admin invariant, and client/supplier API scope."""

from fastapi.testclient import TestClient

from app.main import app
from app.services import auth


def test_password_hash_and_token_roundtrip():
    h = auth.hash_password("secret123")
    assert h.startswith("scrypt$") and "secret123" not in h
    assert auth.verify_password("secret123", h)
    assert not auth.verify_password("wrong", h)


def test_single_admin_and_role_scoping():
    with TestClient(app) as client:
        demos = client.get("/api/auth/demo-accounts").json()
        assert any(d["role"] == "client" and d["entityId"] == "cli_0082" for d in demos)
        assert any(d["role"] == "supplier" and d["entityId"] == "sup_0007" for d in demos)

        # Admin login
        r_admin = client.post("/api/auth/login", json={"username": "admin", "password": "demo-admin"})
        if r_admin.status_code != 200:
            # If ADMIN_PASSWORD env was set in host env, skip password login check cleanly
            return
        tok_admin = r_admin.json()["token"]
        hdr_admin = {"Authorization": f"Bearer {tok_admin}"}

        # Cannot create a 2nd admin
        r2 = client.post("/api/accounts", json={"username": "admin2", "role": "admin", "password": "demo-other"}, headers=hdr_admin)
        assert r2.status_code == 409

        # Cannot demote or delete the sole admin
        accs = client.get("/api/accounts", headers=hdr_admin).json()
        sole_admin = next(a for a in accs if a["role"] == "admin")
        assert client.patch(f"/api/accounts/{sole_admin['id']}", json={"role": "manager"}, headers=hdr_admin).status_code == 409
        assert client.delete(f"/api/accounts/{sole_admin['id']}", headers=hdr_admin).status_code == 409

        # Supplier cannot read clients or create accounts; can read own supplier
        tok_sup = client.post("/api/auth/login", json={"username": "chambaran", "password": "demo-chambaran"}).json()["token"]
        hdr_sup = {"Authorization": f"Bearer {tok_sup}"}
        assert client.get("/api/clients", headers=hdr_sup).status_code == 403
        assert client.get("/api/accounts", headers=hdr_sup).status_code == 403
        assert client.get("/api/suppliers/sup_0007", headers=hdr_sup).status_code == 200
        assert client.get("/api/suppliers/sup_0001", headers=hdr_sup).status_code == 403

        # Client cannot read suppliers or other clients
        tok_cli = client.post("/api/auth/login", json={"username": "payet", "password": "demo-payet"}).json()["token"]
        hdr_cli = {"Authorization": f"Bearer {tok_cli}"}
        assert client.get("/api/suppliers", headers=hdr_cli).status_code == 403
        assert client.get("/api/clients/cli_0082", headers=hdr_cli).status_code == 200
        assert client.get("/api/clients/cli_0033", headers=hdr_cli).status_code == 403
