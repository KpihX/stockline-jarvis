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
