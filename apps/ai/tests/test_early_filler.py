"""Latency work, part 2 (offline): the filler starts when the final transcript is known (before the model), the tool call is announced
when its block STARTS, and the wait phrase is never doubled by the model's own text."""

import asyncio

import pytest

from app.agent import run_agent
from app.clients import LLMText, LLMToolCall, LLMToolStart
from app.schemas import ToolCall, ToolStartEvent
from app.services import turn_hints, voice_session, warmup
from app.tools.registry import Tool, ToolArgs
from tests.test_voice_latency import RecordingTTS, ScriptedLLM, _lookup, call, done_message, session  # noqa: F401  (session = fixture)

# ── the heuristic ──


@pytest.mark.parametrize(
    "text",
    [
        "Bonjour, il vous reste du Beaufort d'alpage en stock ?",
        "C'est combien le kilo de comté dix-huit mois, s'il vous plaît ?",
        "Je voudrais la même chose que d'habitude pour demain",
        "Ajoutez 3 kilos de reblochon",
        "Ici le Chalet du Recoin",  # five words, a request in the making: more likely a lookup than small talk
        "Vous avez du bar ?",
    ],
)
def test_business_turns_get_the_filler(text):
    assert turn_hints.likely_needs_tools(text)


@pytest.mark.parametrize(
    "text",
    ["Bonjour", "Bonjour !", "Merci beaucoup", "Oui", "Non.", "D'accord, merci", "Oui merci", "Très bien, parfait", "Au revoir et bonne journée", "Allo ?", "C'est tout", "ok", "", "   "],
)
def test_trivial_turns_do_not(text):
    assert not turn_hints.likely_needs_tools(text)


def test_filler_is_skipped_when_one_was_played_a_moment_ago():
    assert turn_hints.should_prefill("il vous reste du beaufort ?", None)
    assert turn_hints.should_prefill("il vous reste du beaufort ?", turn_hints.FILLER_MIN_GAP_S + 1)
    assert not turn_hints.should_prefill("il vous reste du beaufort ?", 3.0)
    assert not turn_hints.should_prefill("merci", None)


# ── a whole turn ──


def filler_texts():
    return set(warmup.FILLERS)


async def test_filler_is_requested_before_the_model_call_starts(session, monkeypatch):  # noqa: F811
    order: list[str] = []
    conn, conv, tts = session([[call()], [LLMText("Il en reste douze kilos.")]])
    real_stream, real_synth = ScriptedLLM.stream, RecordingTTS.synthesize

    async def stream(self, request):
        await asyncio.sleep(0.05)  # the model takes its time: the filler must not wait for it
        order.append("llm")
        async for ev in real_stream(self, request):
            yield ev

    async def synth(self, text, voice=None):
        order.append("tts:filler" if text in filler_texts() else "tts:answer")
        return await real_synth(self, text, voice)

    monkeypatch.setattr(ScriptedLLM, "stream", stream)
    monkeypatch.setattr(RecordingTTS, "synthesize", synth)
    await conn.run_turn(conv, text="il vous reste du beaufort en stock ?")
    assert order[:2] == ["tts:filler", "llm"]
    assert tts.said[0] in filler_texts() and tts.said[1:] == ["Il en reste douze kilos."]
    assert sum(t in filler_texts() for t in tts.said) == 1  # one filler, not one at the transcript and another at the tool call
    assert done_message(conn)["timings"]["firstSoundKind"] == "filler"


async def test_trivial_turn_has_no_filler_even_if_the_model_uses_a_tool(session):  # noqa: F811
    conn, conv, tts = session([[call()], [LLMText("Avec plaisir.")]])
    await conn.run_turn(conv, text="merci beaucoup")
    assert tts.said[1:] == ["Avec plaisir."] and tts.said[0] in filler_texts()  # the tool-call fallback still covers an unexpected tool round
    conn2, conv2, tts2 = session([[LLMText("Avec plaisir. ")]])
    await conn2.run_turn(conv2, text="merci beaucoup")
    assert tts2.said == ["Avec plaisir."]


async def test_second_tool_turn_right_after_a_filler_skips_the_early_filler(session, monkeypatch):  # noqa: F811
    seen = []
    conn, conv, tts = session([[call()], [LLMText("Oui. ")], [LLMText("Voilà. ")]])
    real = voice_session.Speaker.say_filler

    def spy(self):
        seen.append(len(tts.said))
        real(self)

    monkeypatch.setattr(voice_session.Speaker, "say_filler", spy)
    await conn.run_turn(conv, text="il vous reste du beaufort ?")  # tool turn: a filler
    assert len(seen) == 1 and conn.since_filler() is not None
    await conn.run_turn(conv, text="et du comté, il vous en reste ?")  # 'likely tools' but a filler played seconds ago: no new one
    assert len(seen) == 1


async def test_model_text_before_its_first_tool_is_dropped_when_the_filler_already_played(session):  # noqa: F811
    conn, conv, tts = session([[LLMText("Je regarde."), call()], [LLMText("Voilà.")]])
    await conn.run_turn(conv, text="il vous reste du beaufort en stock ?")
    assert tts.said[0] in filler_texts()
    assert tts.said[1:] == ["Voilà."]  # "Je regarde." was NOT spoken after the filler
    assert [t for t in tts.said if t in filler_texts() or t == "Je regarde."].__len__() == 1


async def test_tool_start_shows_the_tool_before_its_arguments_and_triggers_the_filler(session):  # noqa: F811
    conn, conv, tts = session([[LLMToolStart("lookup", "a"), call("a")], [LLMText("Voilà.")]])
    await conn.run_turn(conv, text="il vous reste du beaufort en stock ?")
    tools = [m for m in conn.ws.sent if m["type"] == "agent_tool"]
    assert tools[0] == {"type": "agent_tool", "name": "lookup"}  # started: name only
    assert tools[1]["name"] == "lookup" and tools[1]["args"] == {} and "ok" not in tools[1]  # called: arguments
    assert tools[2]["ok"] is True and "args" not in tools[2]  # done
    assert len(tools) == 3
    assert done_message(conn)["timings"]["firstToolCallMs"] is not None


async def test_tool_start_alone_fills_the_silence_on_a_turn_the_heuristic_missed(session):  # noqa: F811
    conn, conv, tts = session([[LLMToolStart("lookup", "a"), call("a")], [LLMText("Voilà.")]])
    await conn.run_turn(conv, text="beaufort")  # one word: heuristic says no
    assert tts.said[0] in filler_texts() and tts.said[1:] == ["Voilà."]


# ── the loop: ToolStartEvent only when asked (POST /chat must not see it) ──


async def collect_events(announce: bool):
    llm = ScriptedLLM([[LLMToolStart("lookup", "a"), LLMToolCall(ToolCall(id="a", name="lookup", arguments={})), ], [LLMText("ok")]])
    tools = [Tool("lookup", "Lookup", ToolArgs, _lookup)]
    from app.agent import loop as agent_loop

    async def prompt(mode, actor_name=None, *a, **k):
        return "SYS"

    old = agent_loop.build_system_prompt
    agent_loop.build_system_prompt = prompt
    try:
        from app.schemas import ChatMessage

        return [ev async for ev in run_agent([ChatMessage(role="user", content="x")], llm=llm, tools=tools, mode="voice", announce_tools=announce)]
    finally:
        agent_loop.build_system_prompt = old


async def test_loop_announces_tools_only_on_request():
    with_start = await collect_events(True)
    without = await collect_events(False)
    assert [e.type for e in with_start][:3] == ["tool_start", "tool_call", "tool_result"]
    assert isinstance(with_start[0], ToolStartEvent) and with_start[0].name == "lookup" and with_start[0].call_id == "a"
    assert [e.type for e in without][:2] == ["tool_call", "tool_result"]
