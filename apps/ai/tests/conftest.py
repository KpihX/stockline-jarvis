"""Hermetic lexicon: no test reads the real ERP through the vocabulary store (a test that needs data builds its own LexiconStore)."""

import httpx
import pytest

from app.lexicon.store import LexiconStore, store
from app.tools.erp import ErpClient


def down() -> ErpClient:
    """An ERP that is not there: the lexicon must degrade to 'no lexicon', never raise."""

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("erp is down (tests)", request=request)

    return ErpClient("voice_agent", base_url="http://erp.test", http=httpx.AsyncClient(transport=httpx.MockTransport(refuse)))


@pytest.fixture(autouse=True)
def hermetic_lexicon(monkeypatch):
    monkeypatch.setattr(store, "_erp", down)
    store.invalidate()
    fresh = LexiconStore(down)
    monkeypatch.setattr(store, "_catalogue", fresh._catalogue)
    monkeypatch.setattr(store, "_learned", fresh._learned)
    yield


@pytest.fixture(autouse=True)
def hermetic_session_memory(tmp_path):
    """Session memory (services/memory.py): every test gets its own empty SQLite store in tmp_path — never the repo's `.state/`."""
    from app.services import memory

    cfg = memory.MemorySettings(directory=tmp_path / "state", ttl_s=12 * 3600, max_sessions=200, policy=memory.compaction.Policy(), llm_refine=False)
    memory.set_store(memory.SessionStore(cfg))
    yield
    memory.set_store(None)


@pytest.fixture(autouse=True)
def hermetic_jev(monkeypatch):
    """Never call the live Jev API during unit tests unless a test mocks/enables it explicitly."""
    from app.services import jev_router

    jev_router.clear_cache()
    jev_router.reset_latency()
    monkeypatch.setattr(jev_router, "get_jev_client", lambda: None)
    yield
    jev_router.clear_cache()
