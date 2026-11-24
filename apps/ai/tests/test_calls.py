"""Focused unit tests for WhatsApp VoIP Call Desk role boundary, phone resolution, and webhook lifecycle."""

from fastapi.testclient import TestClient

from app.main import app
from app.services import calls as calls_svc


def test_calls_routes_enforce_manager_or_admin_only():
    client = TestClient(app)
    for role in ("unknown", "client", "supplier"):
        r1 = client.get("/calls/active", headers={"x-caller-role": role})
        assert r1.status_code == 403
        r2 = client.get("/wa/status", headers={"x-caller-role": role})
        assert r2.status_code == 403
    r_mgr = client.get("/calls/active", headers={"x-caller-role": "manager"})
    assert r_mgr.status_code == 200
    r_adm = client.get("/calls/config", headers={"x-caller-role": "admin"})
    assert r_adm.status_code == 200


async def test_webhook_call_lifecycle_and_wav_wrapping(monkeypatch, tmp_path):
    monkeypatch.setenv("AI_STATE_DIR", str(tmp_path))
    calls_svc._calls.clear()

    async def fake_resolve(_phone: str):
        return ("cli_0082", "Le Refuge Payet", True)

    monkeypatch.setattr(calls_svc, "_resolve_client_by_phone", fake_resolve)
    res = await calls_svc.handle_webhook({"event": "call.incoming", "call_id": "CALL-TEST-1", "from": "33745717350", "mode": "baileys_voip"})
    assert res["callId"] == "CALL-TEST-1"
    data = calls_svc.get_active_and_recent()
    assert len(data["items"]) == 1
    assert data["items"][0]["clientId"] == "cli_0082"

    wav = calls_svc._synthetic_speech_wav(1.0)
    assert wav[:4] == b"RIFF" and wav[8:12] == b"WAVE"


async def test_calls_reset_preserves_phone_bindings(monkeypatch, tmp_path):
    monkeypatch.setenv("AI_STATE_DIR", str(tmp_path))
    calls_svc._calls.clear()

    class FakeErp:
        def __init__(self, *_a, **_kw):
            pass

        async def get(self, path: str):
            return {"id": "cli_0082", "name": "Le Refuge Payet"}

        async def post(self, path: str):
            assert path == "/api/admin/reset"
            return {"ok": True}

    class FakeAsyncClient:
        def __init__(self, **_kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

        async def post(self, url: str):
            assert url.endswith("/api/admin/reset")

            class _Resp:
                def raise_for_status(self):
                    pass

                def json(self):
                    return {"ok": True}

            return _Resp()

    monkeypatch.setattr(calls_svc, "ErpClient", FakeErp)
    monkeypatch.setattr(calls_svc.httpx, "AsyncClient", FakeAsyncClient)
    await calls_svc.bind_phone_to_client("33745717350", "cli_0082")
    await calls_svc.handle_webhook({"event": "call.incoming", "call_id": "CALL-RESET-1", "from": "33745717350"})
    assert len(calls_svc.get_active_and_recent()["recent"]) == 1

    res = await calls_svc.reset_test_state()
    assert res["ok"] is True
    assert res["preservedBindings"] == 1
    assert calls_svc.get_active_and_recent()["recent"] == []
    assert calls_svc.list_phone_bindings()[0]["clientId"] == "cli_0082"

