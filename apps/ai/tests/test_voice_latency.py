"""V0 latency work (offline): first-segment cut, canned fillers, warm-up, cost estimate. No provider is called."""

import asyncio
import json

import pytest

from app.agent import loop as agent_loop
from app.clients import LLMClient, LLMRequest, LLMText, LLMToolCall, LLMUsage
from app.clients.base import TTSClient, TTSResult
from app.pricing import estimate_cost, llm_usd
from app.schemas import ToolCall, Usage
from app.services import voice_session, warmup
from app.services.voice_session import Speaker, early_cut
from app.tools.registry import Tool, ToolArgs

# ── early_cut: first segment of a turn ──


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Bonjour Patrick, je regarde", "Bonjour Patrick,"),  # comma after ≥ 2 words
        ("Oui, on en a encore", None),  # one word before the comma: not worth a call, and fewer than 7 words
        ("Oui, on en a encore six kilos", "Oui, on en a encore six"),  # …then the 6-word cut
        ("Bonjour Patrick,", None),  # the comma is the last char: the next delta may be a digit
        ("Le kilo est à 18,50 euros pièce", "Le kilo est à 18,50 euros"),  # the decimal comma is not a boundary
        ("Bonjour, que puis-je faire pour vous ? ", None),  # only punctuation would be left: the sentence cut takes it whole
        ("Le kilo de beaufort est à 18,50 euros", "Le kilo de beaufort est à"),
        ("Bonjour", None),
        ("", None),
    ],
)
def test_early_cut(text, expected):
    cut = early_cut(text)
    assert (text[:cut] if cut is not None else None) == expected


def test_early_cut_never_splits_a_decimal_comma():
    text = "Il en reste 18,50 kilos au total"
    cut = early_cut(text)
    assert cut is None or "18,50" in text[:cut]


# ── Speaker ──


class RecordingTTS(TTSClient):
    name = "fake"

    def __init__(self):
        self.said: list[str] = []

    async def synthesize(self, text, voice=None):
        self.said.append(text)

        async def chunks():
            yield b"MP3:" + text.encode()

        return TTSResult("audio/mpeg", chunks())


def make_speaker(tts=None):
    sent, audio = [], []

    async def send(msg):
        sent.append(msg)

    async def send_bytes(b):
        audio.append(b)

    return Speaker(tts or RecordingTTS(), send, send_bytes), sent, audio


async def test_first_segment_cut_at_comma_then_sentences():
    tts = RecordingTTS()
    sp, _, _ = make_speaker(tts)
    for delta in ["Bonjour Patrick", ", je regarde ça ", "tout de suite. Le beaufort", " est à 18,50 euros. Voilà"]:
        sp.push(delta)
    await sp.finish()
    assert tts.said == ["Bonjour Patrick,", "je regarde ça tout de suite.", "Le beaufort est à 18,50 euros.", "Voilà"]


async def test_first_segment_cut_after_six_words_without_punctuation():
    tts = RecordingTTS()
    sp, _, _ = make_speaker(tts)
    sp.push("Nous avons encore du beaufort d'alpage en stock ")
    sp.push("ce matin.")
    await sp.finish()
    assert tts.said == ["Nous avons encore du beaufort d'alpage", "en stock ce matin."]


async def test_no_early_cut_after_a_filler():
    warmup._clips.clear()
    tts = RecordingTTS()
    sp, _, _ = make_speaker(tts)
    sp.say_filler()  # a filler is queued: the answer waits for its sentence boundary
    sp.push("Bonjour Patrick, je regarde ça tout de suite. ")
    await sp.finish()
    assert tts.said[1:] == ["Bonjour Patrick, je regarde ça tout de suite."]


async def test_cached_filler_costs_no_tts_call_and_is_flagged():
    tts = RecordingTTS()
    sp, sent, audio = make_speaker(tts)
    clip = warmup.Clip("Je regarde.", "audio/mpeg", b"CLIP")
    sp.speak(clip.text, "filler", clip)
    sp.push("Le beaufort est en rupture. ")
    await sp.finish()
    assert tts.said == ["Le beaufort est en rupture."]
    assert audio[0] == b"CLIP"
    assert sp.first_sound_kind == "filler"
    assert sp.answer_at and sp.first_byte_at and sp.answer_at >= sp.first_byte_at
    assert sp.tts_chars == len("Le beaufort est en rupture.")
    assert [m.type for m in sent] == ["agent_audio_start", "agent_audio_end"]


def test_choose_filler_varies_and_prefers_cache():
    warmup._last_filler = None
    clips = [warmup.Clip(t, "audio/mpeg", b"x") for t in warmup.FILLERS]
    picks = [warmup.choose_filler(clips) for _ in range(30)]
    assert all(isinstance(p, warmup.Clip) for p in picks)
    assert all(a.text != b.text for a, b in zip(picks, picks[1:]))  # never twice in a row
    assert isinstance(warmup.choose_filler([]), str)  # nothing cached: the text, spoken by the TTS


# ── a whole turn: filler on the first tool call, not twice ──


class ScriptedLLM(LLMClient):
    provider, model = "scripted", "claude-sonnet-5-5"

    def __init__(self, steps):
        self.steps = list(steps)

    async def stream(self, request: LLMRequest):
        for ev in self.steps.pop(0):
            yield ev


class FakeWS:
    def __init__(self):
        self.sent, self.audio = [], []

    async def send_text(self, text):
        self.sent.append(json.loads(text))

    async def send_bytes(self, data):
        self.audio.append(data)


async def _lookup(ctx):
    return {"ok": True}


@pytest.fixture
def session(monkeypatch):
    async def prompt(mode, actor_name=None):
        return "SYS"

    monkeypatch.setattr(agent_loop, "build_system_prompt", prompt)
    monkeypatch.setattr(voice_session, "all_tools", lambda: [Tool("lookup", "Lookup", ToolArgs, _lookup)])
    tts = RecordingTTS()
    monkeypatch.setattr(voice_session, "get_tts_client", lambda: tts)
    warmup._clips.clear()

    def make(steps):
        monkeypatch.setattr(voice_session, "get_llm_client", lambda: ScriptedLLM(steps))
        return voice_session.VoiceConnection(FakeWS()), voice_session.Conversation(id="t"), tts

    return make


def call(id="a"):
    return LLMToolCall(ToolCall(id=id, name="lookup", arguments={}))


def done_message(conn):
    return next(m for m in conn.ws.sent if m["type"] == "agent_done")


async def test_turn_with_tool_starts_with_a_filler_then_the_answer(session):
    usage = LLMUsage(100, 20, cache_creation_input_tokens=0, cache_read_input_tokens=5000)
    conn, conv, tts = session([[call(), usage], [LLMText("Il en reste douze kilos."), usage]])
    await conn.run_turn(conv, text="du beaufort ?")
    assert tts.said[0] in warmup.FILLERS  # nothing cached in this test: synthesised on the spot
    assert tts.said[1:] == ["Il en reste douze kilos."]
    d = done_message(conn)
    assert d["timings"]["firstSoundKind"] == "filler"
    assert d["timings"]["answerMs"] >= d["timings"]["totalMs"]
    assert d["timings"]["firstToolCallMs"] is not None
    assert d["cost"]["llmCacheReadTokens"] == 10000 and d["cost"]["llmInputTokens"] == 200
    assert d["cost"]["ttsChars"] == len(tts.said[0]) + len("Il en reste douze kilos.")


async def test_turn_without_tool_has_no_filler(session):
    conn, conv, tts = session([[LLMText("Bonjour, que puis-je faire pour vous ? ")]])
    await conn.run_turn(conv, text="allo")
    assert not set(tts.said) & set(warmup.FILLERS)
    assert done_message(conn)["timings"]["firstSoundKind"] == "answer"
    assert done_message(conn)["timings"]["answerMs"] == done_message(conn)["timings"]["totalMs"]


async def test_text_said_before_the_tool_is_spoken_at_once_and_replaces_the_filler(session):
    conn, conv, tts = session([[LLMText("Je regarde."), call()], [LLMText("Voilà.")]])
    await conn.run_turn(conv, text="du beaufort ?")
    assert tts.said == ["Je regarde.", "Voilà."]  # no second filler on top of the model's own
    assert done_message(conn)["timings"]["firstSoundKind"] == "answer"


async def test_audio_cancel_drops_a_tap_without_a_turn(monkeypatch):
    from app.clients.mock_speech import MockSTT, MockTTS

    class MockLLM:
        provider, model = "mock", "mock"

    monkeypatch.setattr(voice_session, "get_stt_client", lambda: MockSTT("texte"))
    monkeypatch.setattr(voice_session, "get_tts_client", lambda: MockTTS())
    monkeypatch.setattr(voice_session, "get_llm_client", lambda: MockLLM())
    conn = voice_session.VoiceConnection(FakeWS())
    await conn.handle_text(json.dumps({"type": "audio_start", "mime": "audio/webm"}))
    assert conn.recording is not None
    await conn.handle_text(json.dumps({"type": "audio_cancel"}))
    assert conn.recording is None and conn.turn is None
    assert not [m for m in conn.ws.sent if m["type"] in ("transcript", "error", "agent_done")]
    await conn.handle_text(json.dumps({"type": "audio_cancel"}))  # nothing recording: harmless


# ── warm-up ──


async def test_prime_llm_sends_the_real_prefix_with_max_tokens_1_and_is_throttled(monkeypatch):
    seen: list[LLMRequest] = []

    class Spy(ScriptedLLM):
        async def stream(self, request):
            seen.append(request)
            yield LLMUsage(5, 1, cache_creation_input_tokens=0, cache_read_input_tokens=9000)

    async def prompt(mode, actor_name=None):
        return f"SYS {mode} {actor_name}"

    monkeypatch.setattr(warmup, "build_system_prompt", prompt)
    warmup._llm_warm_at = float("-inf")
    tools = [Tool("lookup", "Lookup", ToolArgs, _lookup)]
    await warmup.prime_llm(Spy([]), tools, "Agent vocal")
    await warmup.prime_llm(Spy([]), tools, "Agent vocal")  # cache touched a moment ago: skipped
    assert len(seen) == 1
    assert seen[0].max_tokens == 1 and seen[0].system == "SYS voice Agent vocal" and [t.name for t in seen[0].tools] == ["lookup"]
    warmup.touch()  # a real turn also counts
    await warmup.prime_llm(Spy([]), tools, None)
    assert len(seen) == 1
    await warmup.prime_llm(Spy([]), tools, None, force=True)
    assert len(seen) == 2


async def test_warm_up_failures_never_escape(monkeypatch):
    class Boom(ScriptedLLM):
        async def stream(self, request):
            raise RuntimeError("provider down")
            yield

    class BoomTTS(RecordingTTS):
        async def synthesize(self, text, voice=None):
            raise RuntimeError("tts down")

    async def prompt(mode, actor_name=None):
        return "SYS"

    monkeypatch.setattr(warmup, "build_system_prompt", prompt)
    warmup._llm_warm_at = warmup._tts_warm_at = float("-inf")
    warmup._clips.clear()
    await warmup.warm_up(Boom([]), BoomTTS(), [], None)  # must not raise
    assert warmup.cached_fillers(BoomTTS()) == []


async def test_keep_alive_pings_only_while_active_and_stops_when_cancelled(monkeypatch):
    pings = []

    async def fake_prime(llm, tools, actor, force=False):
        pings.append(actor)
        warmup.touch()

    monkeypatch.setattr(warmup, "prime_llm", fake_prime)
    monkeypatch.setattr(warmup, "KEEPALIVE_POLL_S", 0.01)
    monkeypatch.setattr(warmup, "KEEPALIVE_S", 0.05)
    warmup.touch()
    task = asyncio.create_task(warmup.keep_warm(ScriptedLLM([]), lambda: [], lambda: "A"))
    await asyncio.sleep(0.3)
    assert len(pings) >= 2  # the cache would have expired in between: pinged again and again
    monkeypatch.setattr(warmup, "KEEPALIVE_ACTIVE_WINDOW_S", 0.0)  # nobody talked recently: no more paid pings
    await asyncio.sleep(0.1)
    n = len(pings)
    await asyncio.sleep(0.2)
    assert len(pings) == n
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


# ── cost ──


def test_llm_cost_sonnet_with_cache():
    usage = Usage(input_tokens=1_000, output_tokens=200, cache_read_input_tokens=23_000, cache_creation_input_tokens=0)
    # 1000×2 + 200×10 + 23000×0.10 = 2000 + 2000 + 2300 = 6300 → $0.0063 per million
    assert llm_usd(usage, "claude-sonnet-5-5") == pytest.approx(0.0063)
    assert llm_usd(usage, "claude-sonnet-5-5-20261001") == pytest.approx(0.0063)  # dated model id
    assert llm_usd(usage, "some-other-model") == 0.0


def test_estimate_cost_adds_stt_and_tts_and_keeps_counts():
    usage = Usage(input_tokens=0, output_tokens=0)
    c = estimate_cost(usage, 36.0, 1000, llm_model="claude-sonnet-5-5", stt="soniox", tts="elevenlabs")
    assert c.estimated_usd == pytest.approx(0.12 / 100 + 0.04)  # 36 s of 3600 s/h × $0.12 + 1000 chars × $0.04/1k
    assert c.stt_seconds == 36.0 and c.tts_chars == 1000
    mock = estimate_cost(None, 0, 0, llm_model="mock", stt="mock", tts="mock")
    assert mock.estimated_usd == 0 and mock.llm_input_tokens is None
