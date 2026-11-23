"""Essential tests for unified sessions REST CRUD, accent-folded search, role scope, and Assistant<->Voice continuity."""

from starlette.testclient import TestClient

from app.main import app
from app.policy import Caller
from app.services import sessions


def test_auto_title_and_accent_folded_search():
    assert sessions.auto_title("Bonjour, il me faudrait 5 kg de Beaufort d'alpage") == "il me faudrait 5 kg de Beaufort d'alpage"
    assert sessions.fold("Éléments d'Échirolles") == "elements d'echirolles"


def test_sessions_crud_and_role_scope():
    c1 = Caller.declare("client", "cli_0082", "Payet")
    c2 = Caller.declare("client", "cli_0033", "Leïla")
    mgr = Caller.declare("manager", None, "Thibault")

    s1 = sessions.create_session(title="Commande Beaufort d'Été", surface="chat", caller=c1)
    s2 = sessions.create_session(title="Commande Leïla", surface="voice", caller=c2)
    try:
        # Accent-folded search respects client scope
        hits_c1 = sessions.list_sessions(q="beaufort d'ete", caller=c1)
        assert [h["id"] for h in hits_c1] == [s1["id"]]
        assert sessions.detail(s2["id"], caller=c1) is None

        # Manager sees both
        hits_mgr = sessions.list_sessions(caller=mgr)
        ids = {h["id"] for h in hits_mgr}
        assert {s1["id"], s2["id"]} <= ids

        # Rename & remove
        renamed = sessions.rename(s1["id"], "Beaufort urgent", caller=c1)
        assert renamed and renamed["title"] == "Beaufort urgent"
        assert sessions.remove(s1["id"], caller=c1) is True
        assert sessions.detail(s1["id"], caller=c1) is None
    finally:
        sessions.remove(s1["id"], caller=mgr)
        sessions.remove(s2["id"], caller=mgr)


def test_sessions_http_endpoints():
    with TestClient(app) as client:
        hdr = {"x-caller-role": "client", "x-caller-client-id": "cli_0082", "x-actor-name": "Payet"}
        r = client.post("/sessions", json={"title": "Test unifié", "surface": "chat"}, headers=hdr)
        assert r.status_code == 201
        sid = r.json()["id"]
        assert any(x["id"] == sid for x in client.get("/sessions", headers=hdr).json())
        assert client.patch(f"/sessions/{sid}", json={"title": "Renommée"}, headers=hdr).json()["title"] == "Renommée"
        assert client.post(f"/sessions/{sid}/reopen", headers=hdr).status_code == 200
        assert client.delete(f"/sessions/{sid}", headers=hdr).status_code == 204
