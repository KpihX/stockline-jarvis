"""Lexicon at runtime: STT terms (client first, budget), the annotation of a spoken turn, caller identification."""

import asyncio

import pytest

from app.clients.soniox import MAX_TERMS_CHARS, SonioxSTT
from app.lexicon import runtime
from app.lexicon.store import LexiconStore
from app.services import utterance, vocabulary
from app.services.utterance import Utterance
from tests.test_lexicon_learning import SHEETS, FakeErp


@pytest.fixture
def live_store(monkeypatch):
    """The global lexicon store, wired to a fake ERP that has data."""
    import app.lexicon.store as store_module

    fake = FakeErp()
    fresh = LexiconStore(fake.erp)
    for name in ("_catalogue", "_learned", "_erp"):
        monkeypatch.setattr(store_module.store, name, getattr(fresh, name))
    monkeypatch.setattr(store_module.store, "_clients", {})
    return fake


def test_caller_of_reads_the_client_a_tool_works_on():
    assert runtime.caller_of("get_client", {"clientId": "cli_0006"}) == "cli_0006"
    assert runtime.caller_of("create_draft_order", {"clientId": "cli_0006", "lines": []}) == "cli_0006"
    assert runtime.caller_of("search", {"clientId": "cli_0006"}) is None  # not a tool about the caller
    assert runtime.caller_of("get_client", {"clientId": "sup_0001"}) is None and runtime.caller_of("get_client", {}) is None


async def test_stt_hint_puts_the_client_terms_first_then_the_global_ones(monkeypatch):
    async def terms():
        return ["Lemoine", "loup", "Le Refuge Payet"]

    async def mine(client_id):
        return ["Le Refuge Payet", "Josiane"] if client_id == "cli_0001" else []

    monkeypatch.setattr(vocabulary, "company_terms", terms)
    monkeypatch.setattr(vocabulary.store, "client_terms", mine)
    assert await vocabulary.stt_hint("soniox", None, "cli_0001") == "Le Refuge Payet, Josiane, Lemoine, loup"  # deduplicated, client first
    assert await vocabulary.stt_hint("soniox", "cèpes, morilles", "cli_0001") == "cèpes, morilles, Le Refuge Payet, Josiane, Lemoine, loup"
    assert await vocabulary.stt_hint("soniox", None, None) == "Lemoine, loup, Le Refuge Payet"  # first turn: global only
    assert await vocabulary.stt_hint("mock", "texte", "cli_0001") == "texte"


def test_the_clients_terms_survive_the_stt_budget():
    stt = SonioxSTT("k")
    global_terms = [f"produit numéro {i} " + "x" * 40 for i in range(500)]  # far more than MAX_TERMS_CHARS
    hint = ", ".join(["Le Refuge Payet", "Josiane", *global_terms])
    terms = stt.start_request(hint)["context"]["terms"]
    assert terms[:2] == ["Le Refuge Payet", "Josiane"] and sum(len(t) for t in terms) <= MAX_TERMS_CHARS and len(terms) < len(global_terms)


async def test_the_hint_is_rebuilt_for_each_utterance_with_the_current_caller(monkeypatch):
    seen = []

    async def spy(stt_name, hint, client_id=None):
        seen.append(client_id)
        return None

    monkeypatch.setattr(utterance, "stt_hint", spy)

    class Quiet:
        name, streams = "x", False

        async def transcribe(self, audio, mime, hint=None):
            return "ok"

    async def no_partial(u):
        pass

    for caller in (None, "cli_0006"):  # first turn: nobody identified; the next one: the caller is known
        u = Utterance(Quiet(), "audio/webm", None, no_partial, client_id=caller)
        u.feed(b"x")
        assert await u.text() == "ok"
    assert seen == [None, "cli_0006"]


async def test_annotate_is_empty_without_an_erp_and_never_raises():
    assert await runtime.annotate("Ici le refuge Paillet", None) == ""  # tests/conftest.py: the ERP is down


async def test_annotate_adds_the_block_for_a_near_miss_and_the_client_usual_products(live_store):
    from tests.test_lexicon_learning import CLIENTS  # noqa: F401

    SHEETS["cli_0001"] = {**SHEETS["cli_0001"], "usual": [{"productId": "prd_0049", "productName": "Magret de canard", "unit": "kg", "avgQty": 4.0, "frequency": 0.9}]}
    text = await runtime.annotate("Ici le refuge Paillet et du ma graie", "cli_0001")
    assert "Le Refuge Payet (client cli_0001)" in text and "Magret de canard (produit prd_0049)" in text and "≈ 4 kg" in text
    assert await runtime.annotate("bonjour, une question", "cli_0001") == ""


async def test_the_lexicon_never_blocks_a_turn_when_it_is_not_loaded_yet(monkeypatch):
    import app.lexicon.store as store_module

    async def slow():
        await asyncio.sleep(5)

    monkeypatch.setattr(store_module.store._catalogue, "get", slow)
    monkeypatch.setattr(store_module.store._catalogue, "loaded", False)
    t = asyncio.get_running_loop().time()
    assert await runtime.annotate("Ici le refuge Paillet") == ""
    assert asyncio.get_running_loop().time() - t < 1.0  # READY_WAIT_S, not 5 s


# ── the voice session: raw transcript for the caller, hints for the model, caller identification ──


def test_voice_session_appends_the_hints_at_the_end_of_the_user_turn_and_tracks_the_caller(monkeypatch, live_store):
    import json

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.clients.mock_speech import MockSTT, MockTTS
    from app.routers import voice as voice_router
    from app.schemas import ChatMessage, DoneEvent, TextEvent, ToolCall, ToolCallEvent, ToolResultEvent
    from app.services import command, voice_session

    class FakeLLM:
        provider, model = "mock", "mock"

    seen_user, utterances = [], []

    async def agent(messages, **kwargs):
        seen_user.append(messages[-1].content)
        yield ToolCallEvent(call=ToolCall(id="t1", name="get_client", arguments={"clientId": "cli_0001"}))
        yield ToolResultEvent(call_id="t1", name="get_client", ok=True, result={}, ms=1)
        yield TextEvent(delta="Le Refuge Payet, c'est bien ça ?")
        yield DoneEvent(message=ChatMessage(role="assistant", content="Le Refuge Payet, c'est bien ça ?"), ms=1)

    real_utterance = voice_session.Utterance

    def spy(*args, **kwargs):
        utterances.append(kwargs.get("client_id"))
        return real_utterance(*args, **kwargs)

    for mod in (voice_session, command):
        monkeypatch.setattr(mod, "get_stt_client", lambda: MockSTT("Ici le refuge Paillet", chunks_per_word=4))
        monkeypatch.setattr(mod, "get_tts_client", lambda: MockTTS())
        monkeypatch.setattr(mod, "get_llm_client", lambda: FakeLLM())
    monkeypatch.setattr(voice_session, "run_agent", agent)
    monkeypatch.setattr(voice_session, "Utterance", spy)
    app = FastAPI()
    app.include_router(voice_router.router)

    def speak(ws):
        ws.send_json({"type": "audio_start", "mime": "audio/webm"})
        ws.send_bytes(b"frame")
        ws.send_json({"type": "audio_end"})
        out = []
        while True:
            frame = ws.receive()
            if frame.get("text") is None:
                continue
            out.append(json.loads(frame["text"]))
            if out[-1]["type"] in ("agent_done", "error"):
                return out

    with TestClient(app).websocket_connect("/voice") as ws:
        ws.send_json({"type": "start", "role": "sales"})  # tracking the caller from tool calls is for internal roles (a declared client keeps its own id)
        assert ws.receive_json()["type"] == "ready"
        first = speak(ws)
        finals = [m for m in first if m["type"] == "transcript" and m["final"]]
        assert finals[0]["text"] == "Ici le refuge Paillet"  # what the caller sees: the raw transcript, never rewritten
        speak(ws)  # second utterance: the caller is known now
    heard, _, block = seen_user[0].partition("\n\n")
    assert heard == "Ici le refuge Paillet" and block.startswith("[Lexique") and "Le Refuge Payet (client cli_0001)" in block
    assert utterances == [None, "cli_0001"]  # first turn: global lexicon; then the identified caller's, rebuilt per utterance
