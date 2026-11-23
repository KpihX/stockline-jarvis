"""
WS /voice — push-to-talk voice sessions (messages: app/schemas/voice.py).

One turn:
    audio_start … binary frames … audio_end   (or a typed `text` message)
      → STT, live: each frame goes to the provider as it arrives (services/utterance.py);
        "transcript" final:false while the caller speaks, then "transcript" final:true soon after audio_end
      → agent (voice mode) streaming "agent_text" / "agent_tool"
      → each finished sentence goes to TTS right away (sentence by sentence = first audio sooner; the very first
        segment is cut at the first comma / after 6 words)
      → on the first tool call, if nothing was said yet: a canned filler ("Je regarde.", pre-synthesised mp3)
      → "agent_audio_start" {mime}, binary audio chunks…, "agent_audio_end"   (one audio segment per turn)
      → "agent_done" {text, timings, cost}   (timings.firstSoundKind: was the first sound a filler or the answer)

At connection open, services/warmup.py warms the TTS, the LLM prompt cache (+ keep-alive) and the filler clips.

Barge-in: a new audio_start / text while the agent is still busy cancels the running turn (asyncio
cancellation); what was heard and said so far stays in the history.
"""

import asyncio
import json
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from contextlib import aclosing, suppress
from dataclasses import dataclass, field
from typing import Literal

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import TypeAdapter, ValidationError

from app.agent import run_agent, sanitize_history
from app.agent.loop import ms_since
from app.clients import STTUpdate, TTSClient, get_llm_client, get_stt_client, get_tts_client
from app.config import settings
from app.pricing import estimate_cost
from app.schemas import (
    AgentAudioEndMessage,
    AgentAudioStartMessage,
    AgentDoneMessage,
    AgentTextMessage,
    AgentToolMessage,
    AudioCancelMessage,
    AudioEndMessage,
    AudioStartMessage,
    ChatMessage,
    DoneEvent,
    ErrorEvent,
    ReadyMessage,
    ResetMessage,
    StartMessage,
    TextEvent,
    TextMessage,
    ToolCallEvent,
    ToolResultEvent,
    TranscriptMessage,
    TurnCost,
    TurnTimings,
    Usage,
    VoiceClientMessage,
    VoiceErrorMessage,
)
from app.schemas.base import WireModel
from app.tools import all_tools

from . import warmup
from .utterance import Utterance
from .vocabulary import stt_hint

client_message = TypeAdapter(VoiceClientMessage)


@dataclass
class Conversation:
    id: str
    actor_name: str | None = None
    history: list[ChatMessage] = field(default_factory=list)


# In memory: a reconnect with the same sessionId continues the conversation.
conversations: dict[str, Conversation] = {}


class VoiceConnection:
    """One WebSocket connection. Reads client messages; runs each turn as a background task."""

    def __init__(self, ws: WebSocket):
        self.ws = ws
        self.conversation: Conversation | None = None
        self.recording: Utterance | None = None  # while the key is down
        self.turn: asyncio.Task | None = None
        self.warm_tasks: list[asyncio.Task] = []  # background warm-up + cache keep-alive, cancelled when the socket closes
        self._send_lock = asyncio.Lock()

    # ── sending ──

    async def send(self, msg: WireModel) -> None:
        await self._send(text=msg.to_json())

    async def send_bytes(self, data: bytes) -> None:
        await self._send(bytes=data)

    async def _send(self, **message) -> None:
        async with self._send_lock:
            with suppress(WebSocketDisconnect, RuntimeError):  # the client is gone: nothing to do
                if message.get("text") is not None:
                    await self.ws.send_text(message["text"])
                else:
                    await self.ws.send_bytes(message["bytes"])

    # ── receiving ──

    async def serve(self) -> None:
        await self.ws.accept()
        try:
            while True:
                frame = await self.ws.receive()
                if frame["type"] == "websocket.disconnect":
                    break
                if frame.get("bytes") is not None:
                    if self.recording:
                        self.recording.feed(frame["bytes"])
                    continue
                await self.handle_text(frame.get("text") or "")
        except WebSocketDisconnect:
            pass
        finally:
            for task in self.warm_tasks:
                task.cancel()  # the keep-alive stops with the session
            await self.interrupt()

    async def handle_text(self, raw: str) -> None:
        try:
            msg = client_message.validate_python(json.loads(raw))
        except (json.JSONDecodeError, ValidationError):
            await self.send(VoiceErrorMessage(message="invalid JSON message"))
            return
        if not self.conversation and not isinstance(msg, StartMessage):
            await self.open()  # no "start" yet: open a fresh conversation

        match msg:
            case StartMessage(session_id=session_id, actor_name=actor_name):
                await self.interrupt()
                await self.open(session_id, actor_name)
            case AudioStartMessage(mime=mime, hint=hint):
                await self.interrupt()  # barge-in
                self.recording = Utterance(get_stt_client(), mime, hint, on_partial=self.send_partial)
            case AudioEndMessage():
                if self.recording:
                    utterance, self.recording = self.recording, None
                    self.start_turn(utterance=utterance)
            case AudioCancelMessage():  # a tap: the key came up right after audio_start, nothing to answer
                if self.recording:
                    self.recording.cancel()
                    self.recording = None
            case TextMessage(text=text):
                await self.interrupt()
                self.start_turn(text=text)
            case ResetMessage():
                await self.interrupt()
                self.conversation.history = []
                await self.open(self.conversation.id)

    async def send_partial(self, update: STTUpdate) -> None:
        await self.send(TranscriptMessage(text=update.text, final=False, stable=update.stable))

    async def open(self, session_id: str | None = None, actor_name: str | None = None) -> None:
        conv = conversations.get(session_id or "") or Conversation(id=session_id or str(uuid.uuid4()))
        if actor_name:
            conv.actor_name = actor_name
        conversations[conv.id] = self.conversation = conv
        llm = get_llm_client()
        await self.send(
            ReadyMessage(session_id=conv.id, stt=get_stt_client().name, tts=get_tts_client().name, llm=f"{llm.provider}:{llm.model}")
        )
        if not self.warm_tasks:
            self.warm_tasks = self.start_warm_up(llm)

    def start_warm_up(self, llm) -> list[asyncio.Task]:
        """Background, failure-tolerant (see warmup.py): so the first real turn finds everything open."""
        tts = get_tts_client()
        # the company vocabulary for the STT now, not when the caller first speaks
        tasks = [asyncio.create_task(warmup.safely("stt hint", stt_hint(get_stt_client().name, None)))]
        if llm.provider != "mock" or tts.name != "mock":
            actor = self.conversation.actor_name if self.conversation else None
            tasks.append(asyncio.create_task(warmup.warm_up(llm, tts, all_tools(), actor)))
        if llm.provider != "mock":  # prompt cache keep-alive while the session is open
            tasks.append(
                asyncio.create_task(warmup.keep_warm(llm, all_tools, lambda: self.conversation.actor_name if self.conversation else None))
            )
        return tasks

    def start_turn(self, **turn_input) -> None:
        self.turn = asyncio.create_task(self.run_turn(self.conversation, **turn_input))

    async def interrupt(self) -> None:
        """Barge-in: drop a recording in progress, stop the running turn and wait until it has cleaned up."""
        if self.recording:
            self.recording.cancel()
            self.recording = None
        if self.turn and not self.turn.done():
            self.turn.cancel()
            with suppress(asyncio.CancelledError):
                await self.turn
        self.turn = None

    # ── one turn ──

    async def run_turn(
        self,
        conv: Conversation,
        text: str | None = None,
        utterance: Utterance | None = None,  # spoken: already being transcribed since audio_start
    ) -> None:
        t0 = time.perf_counter()  # end of caller speech
        timings = TurnTimings()
        usage: Usage | None = None
        llm = get_llm_client()
        heard, spoken = "", ""
        step_text = ""  # what the model said since the last tool result (not yet in `working`)
        working: list[ChatMessage] | None = None
        committed = False
        speaker: Speaker | None = None
        try:
            # 1. Speech → text: with a streaming STT only the last words are left to finalize
            if utterance is not None:
                text = await utterance.text()
                timings.stt_ms = ms_since(t0)  # end of speech → final transcript
            heard = (text or "").strip()
            if not heard:
                await self.send(VoiceErrorMessage(message="Rien entendu — réessayez."))
                return
            await self.send(TranscriptMessage(text=heard, final=True))

            # 2. Agent, on a working copy of the history (committed at the end)
            working = [*conv.history, ChatMessage(role="user", content=heard)]
            speaker = Speaker(get_tts_client(), self.send, self.send_bytes)
            llm_start = time.perf_counter()
            async for ev in run_agent(working, llm=llm, tools=all_tools(), mode="voice", actor_name=conv.actor_name):
                match ev:
                    case TextEvent(delta=delta):
                        if timings.llm_first_token_ms is None:
                            timings.llm_first_token_ms = ms_since(llm_start)
                        spoken += delta
                        step_text += delta
                        await self.send(AgentTextMessage(delta=delta))
                        speaker.push(delta)
                    case ToolCallEvent(call=call):
                        if timings.first_tool_call_ms is None:
                            timings.first_tool_call_ms = ms_since(llm_start)
                        speaker.flush()  # what the model said before the tool is complete: speak it now, not after the tools
                        if not speaker.queued:  # nothing to hear yet: a canned wait phrase instead of silence
                            speaker.say_filler()
                        await self.send(AgentToolMessage(name=call.name, args=call.arguments))
                    case ToolResultEvent(name=name, ok=ok, ms=ms):
                        step_text = ""
                        await self.send(AgentToolMessage(name=name, ok=ok, ms=ms))
                    case DoneEvent(usage=done_usage):
                        usage = done_usage
                    case ErrorEvent(message=message):
                        await self.send(VoiceErrorMessage(message=message))
            timings.llm_total_ms = ms_since(llm_start)
            warmup.touch()  # the model call just read the prompt cache: its 5-minute TTL restarted
            conv.history = trim(working)
            committed = True

            # 3. Speak the last sentence and wait until all the audio is sent
            await speaker.finish()
            timings.tts_first_byte_ms = speaker.tts_first_byte_ms
            timings.first_sound_kind = speaker.first_sound_kind
            if speaker.first_byte_at:
                timings.total_ms = int((speaker.first_byte_at - t0) * 1000 + 0.5)
            if speaker.answer_at:
                timings.answer_ms = int((speaker.answer_at - t0) * 1000 + 0.5)
            stt_seconds = utterance.audio_seconds if utterance else 0.0
            cost = estimate_cost(usage, stt_seconds, speaker.tts_chars, llm_model=llm.model, stt=get_stt_client().name, tts=speaker.tts.name)
            log_turn(timings, cost)
            await self.send(AgentDoneMessage(text=spoken.strip(), timings=timings, cost=cost))

        except asyncio.CancelledError:
            # Interrupted: keep what was heard, the tool rounds already done (an order the agent created must stay
            # known) and what the agent had started to say. Not when the turn was already committed (barge-in during
            # the last sentence's audio): that would duplicate it. trim() closes a tool call cut mid-run.
            if heard and not committed:
                kept = working if working is not None else [*conv.history, ChatMessage(role="user", content=heard)]
                last = kept[-1]
                if step_text.strip() and not (last.role == "assistant" and last.tool_calls):
                    kept = [*kept, ChatMessage(role="assistant", content=f"{step_text.strip()} …")]
                conv.history = trim(kept)
            if speaker:
                await speaker.stop()
            raise
        except Exception as e:
            await self.send(VoiceErrorMessage(message=str(e) or type(e).__name__))
        finally:
            if utterance:
                utterance.cancel()  # interrupted while transcribing: close the provider stream


EARLY_MIN_WORDS = 2  # a comma after a single word ("Oui,") is not worth a TTS call of its own
EARLY_MAX_WORDS = 6  # no punctuation yet: cut after this many words


def early_cut(text: str) -> int | None:
    """Where the FIRST segment of a turn can already be cut, to start speaking sooner: after the first comma that
    follows at least EARLY_MIN_WORDS words, or after EARLY_MAX_WORDS words. None = keep waiting for more text.
    A word is only judged once whitespace follows it, so "18,50" split across two deltas ("18," + "50") is never a cut,
    and a comma between digits is a decimal separator, not a boundary."""
    for n, m in enumerate(re.finditer(r"\S+", text), start=1):
        if m.end() >= len(text):
            return None  # the last word may still grow
        if m.group().endswith(",") and n >= EARLY_MIN_WORDS:
            return m.end()
        if n >= EARLY_MAX_WORDS and re.search(r"\w", text[m.end() :]):  # (not for a lone "?" that the sentence cut takes whole)
            return m.end()
    return None


@dataclass
class Segment:
    """One thing to say: text for the TTS, or a canned `clip` (already synthesised audio, no TTS call)."""

    text: str
    kind: Literal["filler", "answer"] = "answer"
    clip: warmup.Clip | None = None


class Speaker:
    """Buffers the streamed text, cuts it into sentences and speaks them in order, as one audio segment."""

    # a sentence ends with . ! ? … followed by a space ("18.50" is not a boundary)
    SENTENCE = re.compile(r"^([\s\S]*?[.!?…])\s+")

    def __init__(self, tts: TTSClient, send: Callable[[WireModel], Awaitable], send_bytes: Callable[[bytes], Awaitable]):
        self.tts, self.send, self.send_bytes = tts, send, send_bytes
        self.buffer = ""
        self.sentences: asyncio.Queue[Segment | None] = asyncio.Queue()
        self.worker: asyncio.Task | None = None  # speaks the queued sentences one after the other
        self.queued = 0  # segments queued so far (filler included)
        self.started = False
        self.mime: str | None = None
        self.first_byte_at: float | None = None  # first audio byte of any kind
        self.first_sound_kind: Literal["filler", "answer"] | None = None
        self.answer_at: float | None = None  # first audio byte of the real answer
        self.tts_first_byte_ms: int | None = None  # of the first sentence that went through the TTS
        self.tts_chars = 0  # characters sent to the TTS (canned clips are free)

    def push(self, delta: str) -> None:
        self.buffer += delta
        while (end := self.next_cut()) is not None:
            self.speak(self.buffer[:end])
            self.buffer = self.buffer[end:]

    def next_cut(self) -> int | None:
        m = self.SENTENCE.match(self.buffer)
        end = m.end() if m else None
        if not self.queued:  # first segment of the turn, nothing playing yet: the comma / 6-word cut brings the first sound sooner
            early = early_cut(self.buffer)
            if early is not None and (end is None or early < end):
                return early
        return end

    def speak(self, sentence: str, kind: Literal["filler", "answer"] = "answer", clip: warmup.Clip | None = None) -> None:
        sentence = sentence.strip()
        if not sentence:
            return
        if self.worker is None:
            self.worker = asyncio.create_task(self._speak_queued())
        self.queued += 1
        self.sentences.put_nowait(Segment(sentence, kind, clip))

    def flush(self) -> None:
        """Speak the buffered text now (the model is done talking for this step: it calls a tool)."""
        self.speak(self.buffer)
        self.buffer = ""

    def say_filler(self) -> None:
        """A short varied wait phrase: the pre-synthesised mp3 when cached (no TTS call), else synthesised on the spot."""
        pick = warmup.choose_filler(warmup.cached_fillers(self.tts))
        if isinstance(pick, str):
            self.speak(pick, "filler")
        else:
            self.speak(pick.text, "filler", pick)

    async def finish(self) -> None:
        """Speak what is left in the buffer, wait for all the audio, close the segment."""
        self.flush()
        if self.worker:
            self.sentences.put_nowait(None)
            await self.worker
        if self.started:
            await self.send(AgentAudioEndMessage())

    async def stop(self) -> None:
        """Interrupted: drop the queued sentences, close the segment if audio was sent."""
        if self.worker:
            self.worker.cancel()
            with suppress(asyncio.CancelledError):
                await self.worker
        if self.started:
            await self.send(AgentAudioEndMessage())

    async def _speak_queued(self) -> None:
        while (seg := await self.sentences.get()) is not None:
            tts_start = time.perf_counter()
            try:
                if seg.clip:  # canned filler: no TTS call. Skipped if the segment already started with another audio format.
                    if self.mime in (None, seg.clip.mime):
                        await self._audio_chunk(seg, seg.clip.mime, seg.clip.data, None)
                    continue
                self.tts_chars += len(seg.text)
                result = await self.tts.synthesize(seg.text, settings.tts.voice or None)
                # aclosing: on barge-in (cancellation) the provider's HTTP stream is closed right away
                async with aclosing(result.chunks) as chunks:  # type: ignore[type-var]
                    async for chunk in chunks:
                        await self._audio_chunk(seg, result.mime, chunk, tts_start)
            except Exception as e:
                await self.send(VoiceErrorMessage(message=f"TTS : {e}"))

    async def _audio_chunk(self, seg: Segment, mime: str, chunk: bytes, tts_start: float | None) -> None:
        """Send audio of `seg`; the first chunk of the turn opens the audio segment on the client."""
        now = time.perf_counter()
        if not self.started:
            self.started, self.mime = True, mime
            await self.send(AgentAudioStartMessage(mime=mime))
            self.first_byte_at, self.first_sound_kind = now, seg.kind
        if seg.kind == "answer" and self.answer_at is None:
            self.answer_at = now
        if tts_start is not None and self.tts_first_byte_ms is None:
            self.tts_first_byte_ms = ms_since(tts_start)
        await self.send_bytes(chunk)


def log_turn(timings: TurnTimings, cost: TurnCost) -> None:
    """One line per turn in the service logs: what to read when comparing techniques."""
    print(
        f"[turn] stt={timings.stt_ms}ms llm1={timings.llm_first_token_ms}ms tool1={timings.first_tool_call_ms}ms llm={timings.llm_total_ms}ms "
        f"ttsFirst={timings.tts_first_byte_ms}ms total={timings.total_ms}ms answer={timings.answer_ms}ms firstSound={timings.first_sound_kind} | "
        f"tokens in={cost.llm_input_tokens} out={cost.llm_output_tokens} cacheRead={cost.llm_cache_read_tokens} cacheWrite={cost.llm_cache_creation_tokens} "
        f"stt={cost.stt_seconds}s tts={cost.tts_chars}chars ≈ ${cost.estimated_usd} (€{cost.estimated_eur}, estimate)",
        flush=True,
    )


def trim(history: list[ChatMessage], max_messages: int = 40) -> list[ChatMessage]:
    """Keep the last ~40 messages, starting on a user message (never split a tool call from its result)."""
    history = sanitize_history(history)  # no dangling tool call (cancelled mid-tool), no orphan result
    if len(history) <= max_messages:
        return history
    start = next((i for i, m in enumerate(history) if i >= len(history) - max_messages and m.role == "user"), -1)
    return history[start:] if start > 0 else history

