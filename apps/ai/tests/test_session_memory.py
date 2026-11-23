"""Session memory (services/memory.py): persistence round trip, TTL, cap, corrupted / unwritable store, rebased commit, background compaction,
and a whole voice session that survives a "restart" (a brand-new in-memory registry over the same SQLite file)."""

import asyncio
import json
import os
import sqlite3

import pytest

from app.schemas import ChatMessage, ToolCall
from app.services import compaction, memory, voice_session
from app.services.memory import MemorySettings, SessionStore
from tests.test_compaction import assert_paired, chatter, order_call


def cfg(tmp_path, **kw) -> MemorySettings:
    base = dict(directory=tmp_path / "state", ttl_s=3600.0, max_sessions=5, policy=compaction.Policy(), llm_refine=False)
    return MemorySettings(**{**base, **kw})


class Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


def history():
    return [
        ChatMessage(role="user", content="du beaufort ?"),
        ChatMessage(role="assistant", content="Je regarde", tool_calls=[ToolCall(id="a", name="search", arguments={"query": "beaufort", "n": 1})]),
        ChatMessage(role="tool", tool_call_id="a", name="search", content='[{"id":"prd_0031","label":"Beaufort d\'alpage"}]'),
        ChatMessage(role="assistant", content="Oui, 12 kilos."),
    ]


# ── store ──


def test_round_trip_keeps_messages_tool_calls_and_meta(tmp_path):
    s = SessionStore(cfg(tmp_path))
    s.save("s1", {"actor_name": "Agent vocal", "client_id": "cli_0012", "facts": {"k": [1, 2]}}, history())
    s.close()
    again = SessionStore(cfg(tmp_path))  # a new process over the same file
    meta, loaded = again.load("s1")
    assert meta == {"actor_name": "Agent vocal", "client_id": "cli_0012", "facts": {"k": [1, 2]}}
    assert loaded == history() and loaded[1].tool_calls[0].arguments == {"query": "beaufort", "n": 1}
    assert again.load("unknown") is None


def test_ttl_expired_session_is_not_restored_and_is_deleted(tmp_path):
    clock = Clock()
    s = SessionStore(cfg(tmp_path, ttl_s=100), clock)
    s.save("old", {}, history())
    clock.t += 99
    assert s.load("old") is not None
    clock.t += 2  # 101 s since the last write
    assert s.load("old") is None
    assert s.count() == 0


def test_a_write_refreshes_the_ttl(tmp_path):
    clock = Clock()
    s = SessionStore(cfg(tmp_path, ttl_s=100), clock)
    s.save("a", {}, history())
    clock.t += 90
    s.save("a", {}, history())  # a new committed turn
    clock.t += 90
    assert s.load("a") is not None


def test_cap_evicts_the_oldest_sessions_first_and_reports_them(tmp_path):
    clock = Clock()
    s = SessionStore(cfg(tmp_path, max_sessions=3), clock)
    for i in range(3):
        clock.t += 1
        assert s.save(f"s{i}", {}, history()) == []
    clock.t += 1
    s.save("s0", {}, history())  # s0 is the most recently used now: s1 is the oldest
    clock.t += 1
    assert s.save("s3", {}, history()) == ["s1"]
    assert {i for i in ("s0", "s1", "s2", "s3") if s.load(i)} == {"s0", "s2", "s3"}
    assert s.count() == 3


def test_expired_rows_are_purged_by_a_later_save(tmp_path):
    clock = Clock()
    s = SessionStore(cfg(tmp_path, ttl_s=100), clock)
    s.save("old", {}, history())
    clock.t += 500
    assert "old" in s.save("new", {}, history())
    assert s.count() == 1


def test_delete(tmp_path):
    s = SessionStore(cfg(tmp_path))
    s.save("s", {}, history())
    s.delete("s")
    assert s.load("s") is None


def test_a_corrupted_database_file_is_moved_aside_and_the_store_starts_empty(tmp_path, capsys):
    d = tmp_path / "state"
    d.mkdir()
    (d / "sessions.db").write_bytes(b"this is definitely not an sqlite database" * 50)
    s = SessionStore(cfg(tmp_path))
    assert s.load("x") is None
    s.save("x", {}, history())
    assert s.load("x") is not None  # working again
    assert [p.name for p in d.iterdir() if ".corrupt-" in p.name]  # the evidence is kept
    assert "corrupted session database" in capsys.readouterr().out


def test_a_corrupted_row_is_dropped_not_raised(tmp_path):
    s = SessionStore(cfg(tmp_path))
    s.save("bad", {}, history())
    db = sqlite3.connect(tmp_path / "state" / "sessions.db")
    db.execute("UPDATE sessions SET history='{not json' WHERE id='bad'")
    db.commit()
    db.close()
    assert s.load("bad") is None
    assert s.count() == 0


def test_unwritable_directory_falls_back_to_memory_and_logs_once(tmp_path, capsys):
    blocker = tmp_path / "state"
    blocker.write_text("a FILE where the directory should be")  # mkdir fails
    s = SessionStore(cfg(tmp_path))
    assert s.save("s", {}, history()) == []
    assert s.load("s") is None
    s.delete("s")
    assert s.count() == 0 and not s.enabled
    assert capsys.readouterr().out.count("persistence OFF") == 1  # once, not once per call


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_read_only_directory_falls_back_to_memory(tmp_path):
    d = tmp_path / "state"
    d.mkdir()
    d.chmod(0o500)
    try:
        s = SessionStore(cfg(tmp_path))
        assert s.save("s", {}, history()) == [] and s.load("s") is None and not s.enabled
    finally:
        d.chmod(0o700)


# ── Conversation glue ──


def test_conversation_fields_including_the_declared_caller_round_trip(tmp_path):
    from app.policy import Caller

    memory.set_store(SessionStore(cfg(tmp_path)))
    conv = voice_session.Conversation(id="c1", actor_name="Agent vocal", history=history(), client_id="cli_0012", session_block="BLOCK", facts={"x": 1})
    conv.caller = Caller.declare("client", "cli_0012", "Chalet du Recoin")
    memory.persist(conv)
    memory.set_store(SessionStore(cfg(tmp_path)))  # "restart"
    back = memory.restore(voice_session.Conversation, "c1")
    assert back.history == history() and back.client_id == "cli_0012" and back.session_block == "BLOCK" and back.facts == {"x": 1}
    assert back.caller == conv.caller and isinstance(back.caller, Caller)  # same identity: reconnecting does NOT wipe the history
    assert memory.restore(voice_session.Conversation, "nope") is None and memory.restore(voice_session.Conversation, "") is None


def test_commit_sanitises_and_persists(tmp_path):
    memory.set_store(SessionStore(cfg(tmp_path)))
    conv = voice_session.Conversation(id="c2")
    cut = [*history()[:2]]  # a tool call without its result (turn cut mid-tool)
    base = conv.history
    memory.commit(conv, base, [ChatMessage(role="user", content="x"), *cut])
    assert_paired(conv.history)
    assert memory.restore(voice_session.Conversation, "c2").history == conv.history


def test_commit_rebases_onto_a_history_compacted_meanwhile():
    conv = voice_session.Conversation(id="c3", history=[*order_call(), *chatter(14)])
    base = conv.history
    working = [*base, ChatMessage(role="user", content="encore une question"), ChatMessage(role="assistant", content="Voilà.")]  # the turn in flight
    compacted, facts, _ = compaction.compact(base)
    conv.history, conv.facts = compacted, facts  # the background compaction lands first
    memory.commit(conv, base, working)
    assert compaction.is_summary(conv.history[0]) and [m.content for m in conv.history[-2:]] == ["encore une question", "Voilà."]
    assert len(conv.history) == len(compacted) + 2  # nothing lost, nothing duplicated, the compaction is not undone


# ── background compaction ──


async def test_compact_later_folds_persists_and_reloads(tmp_path):
    memory.set_store(SessionStore(cfg(tmp_path)))
    conv = voice_session.Conversation(id="c4", history=[*order_call(), *chatter(14)])
    assert await memory.compact_later(conv) is True
    assert compaction.is_summary(conv.history[0]) and conv.facts["orders"]["ord_0345"]["lines"][0]["qty"] == 10
    assert_paired(conv.history)
    back = memory.restore(voice_session.Conversation, "c4")
    assert back.history == conv.history and back.facts == conv.facts
    assert await memory.compact_later(conv) is False  # already small: nothing to do


async def test_compact_later_gives_up_if_the_history_changed_meanwhile():
    conv = voice_session.Conversation(id="c5", history=[*order_call(), *chatter(14)])
    original = conv.history

    real = compaction.compact

    def racy(base, facts, policy):
        conv.history = [*base, ChatMessage(role="user", content="a new turn was committed")]  # a turn landed while we were computing
        return real(base, facts, policy)

    old, compaction.compact = compaction.compact, racy
    try:
        assert await memory.compact_later(conv) is False
    finally:
        compaction.compact = old
    assert conv.history[-1].content == "a new turn was committed" and conv.history[0] is original[0]


async def test_compact_later_never_raises(monkeypatch, capsys):
    conv = voice_session.Conversation(id="c6", history=[*order_call(), *chatter(14)])
    monkeypatch.setattr(compaction, "compact", lambda *a, **k: 1 / 0)
    assert await memory.compact_later(conv) is False
    assert "compaction failed" in capsys.readouterr().out
    assert len(conv.history) > 20  # untouched


async def test_llm_refinement_is_applied_in_the_background_when_valid_and_ignored_when_not(tmp_path):
    from app.clients import LLMText

    class LLM:
        provider, model = "scripted", "m"

        def __init__(self, reply):
            self.reply = reply

        async def stream(self, request):
            yield LLMText(self.reply)

    memory.set_store(SessionStore(cfg(tmp_path)))
    conv = voice_session.Conversation(id="c7", history=[*order_call(), *chatter(14)])
    assert await memory.compact_later(conv, LLM(f"{compaction.SUMMARY_MARK} : cli_0012 ord_0345 prd_0056 10 kg diots 8.5 jeudi 26.]"), refine=True)
    assert conv.history[0].content.endswith("jeudi 26.]") and len(conv.history[0].content) < 200
    conv2 = voice_session.Conversation(id="c8", history=[*order_call(), *chatter(14)])
    await memory.compact_later(conv2, LLM("résumé sans identifiants"), refine=True)
    assert "ord_0345" in conv2.history[0].content  # the invalid refinement was rejected: the deterministic summary stays


# ── a whole voice session ──


class FakeWS:
    def __init__(self):
        self.sent, self.audio = [], []

    async def send_text(self, text):
        self.sent.append(json.loads(text))

    async def send_bytes(self, data):
        self.audio.append(data)


@pytest.fixture
def conn_factory(monkeypatch):
    from app.clients.mock_speech import MockSTT, MockTTS

    class MockLLM:
        provider, model = "mock", "mock"

    monkeypatch.setattr(voice_session, "get_stt_client", lambda: MockSTT("texte"))
    monkeypatch.setattr(voice_session, "get_tts_client", lambda: MockTTS())
    monkeypatch.setattr(voice_session, "get_llm_client", lambda: MockLLM())
    monkeypatch.setattr(voice_session, "conversations", {})

    async def start(session_id=None):
        conn = voice_session.VoiceConnection(FakeWS())
        await conn.handle_text(json.dumps({"type": "start", **({"sessionId": session_id} if session_id else {})}))
        return conn

    return start


async def test_a_session_survives_a_restart_and_reset_forgets_it(conn_factory, monkeypatch):
    from app.agent import loop as agent_loop
    from app.clients import LLMText
    from tests.test_voice_latency import ScriptedLLM

    class OfflineLLM(ScriptedLLM):
        provider = "mock"  # no warm-up task, no keep-alive

    async def prompt(mode, actor_name=None, *a, **k):
        return "SYS"

    monkeypatch.setattr(agent_loop, "build_system_prompt", prompt)
    conn = await conn_factory("keep-me")
    conv = conn.conversation
    conv.history = [ChatMessage(role="user", content="avant"), ChatMessage(role="assistant", content="d'accord")]
    monkeypatch.setattr(voice_session, "get_llm_client", lambda: OfflineLLM([[LLMText("Bonjour.")]]))
    await conn.run_turn(conv, text="un tour de plus")
    assert [m.content for m in conv.history][-2:] == ["un tour de plus", "Bonjour."]
    await asyncio.sleep(0)  # let the background compaction task run (nothing to fold here)

    monkeypatch.setattr(voice_session, "conversations", {})  # uvicorn hot reload: the in-memory registry is gone
    conn2 = await conn_factory("keep-me")
    assert [m.content for m in conn2.conversation.history] == ["avant", "d'accord", "un tour de plus", "Bonjour."]

    await conn2.handle_text(json.dumps({"type": "reset"}))
    assert memory.get_store().load("keep-me") is None  # reset deleted the stored session
    monkeypatch.setattr(voice_session, "conversations", {})
    conn3 = await conn_factory("keep-me")
    assert conn3.conversation.history == []
