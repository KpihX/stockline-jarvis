"""
WS /voice contract: push-to-talk sessions, two tracks (the human "caller" and the agent).

Client → server: JSON messages below, plus binary audio frames between audio_start and audio_end.
Server → client: JSON messages below, plus binary audio frames between agent_audio_start and agent_audio_end.
"""

from typing import Annotated, Any, Literal, Union

from pydantic import Field

from .base import WireModel
from .chat import CallerRole, TurnCost, TurnTimings

# ── Client → server ──


class StartMessage(WireModel):
    """Opens a conversation (same sessionId again = keep the history)."""

    type: Literal["start"] = "start"
    session_id: str | None = None
    token: str | None = None  # optional Bearer token (verified by app/auth.py against GET /api/auth/me)
    actor_name: str | None = None  # declared name of the caller: author of the ERP writes of the session
    role: CallerRole | None = None  # DECLARED role fallback (when ALLOW_DECLARED_IDENTITY=1 and no token).
    client_id: str | None = None  # cli_… the caller is bound to (role client), or the client a manager works on.
    supplier_id: str | None = None  # sup_… the caller is bound to (role supplier).


class AudioStartMessage(WireModel):
    """Caller pressed the talk key; binary frames follow."""

    type: Literal["audio_start"] = "audio_start"
    mime: str
    hint: str | None = None  # optional STT hint (vocabulary; mock STT: the transcript), like x-mock-text on POST /command


class AudioEndMessage(WireModel):
    """Caller released the key: the frames received since audio_start are the utterance (already streamed to the
    STT as they arrived: send them every 100–250 ms, e.g. MediaRecorder.start(100))."""

    type: Literal["audio_end"] = "audio_end"


class AudioCancelMessage(WireModel):
    """Caller released the key almost at once (a tap, a click): drop the recording started by audio_start, no turn."""

    type: Literal["audio_cancel"] = "audio_cancel"


class TextMessage(WireModel):
    """Typed instead of spoken (debug)."""

    type: Literal["text"] = "text"
    text: str


class ResetMessage(WireModel):
    type: Literal["reset"] = "reset"


VoiceClientMessage = Annotated[
    Union[StartMessage, AudioStartMessage, AudioEndMessage, AudioCancelMessage, TextMessage, ResetMessage],
    Field(discriminator="type"),
]

# ── Server → client ──


class ReadyMessage(WireModel):
    type: Literal["ready"] = "ready"
    session_id: str
    stt: str
    tts: str
    llm: str
    role: CallerRole = "unknown"  # the identity the server will ENFORCE
    client_id: str | None = None
    supplier_id: str | None = None
    actor_name: str | None = None
    verified: bool = False


class TranscriptMessage(WireModel):
    """What the caller said. While they speak (streaming STT): final=false, the whole text heard so far, sent again
    as words are recognised; `stable` is its leading part made of final words (will not change, the rest may).
    Then once final=true with the definitive text, which the agent answers."""

    type: Literal["transcript"] = "transcript"
    track: Literal["caller"] = "caller"
    text: str
    final: bool
    stable: str | None = None


class AgentTextMessage(WireModel):
    type: Literal["agent_text"] = "agent_text"
    delta: str


class AgentToolMessage(WireModel):
    """Sent up to three times per tool: (1) `name` only, when the model STARTS the call (Anthropic; the arguments are still streaming),
    (2) with `args` when the call is complete, (3) with `ok`/`ms` when it is done. Providers that cannot tell early skip (1);
    a client pairs (2) with the open (1) of the same name."""

    type: Literal["agent_tool"] = "agent_tool"
    name: str
    ok: bool | None = None
    ms: int | None = None
    args: dict[str, Any] | None = None
    result: Any | None = None


class AgentAudioStartMessage(WireModel):
    """Binary audio frames follow (one segment per turn)."""

    type: Literal["agent_audio_start"] = "agent_audio_start"
    mime: str


class AgentAudioEndMessage(WireModel):
    type: Literal["agent_audio_end"] = "agent_audio_end"


class AgentDoneMessage(WireModel):
    type: Literal["agent_done"] = "agent_done"
    text: str
    timings: TurnTimings
    cost: TurnCost | None = None  # tokens, STT seconds, TTS characters and their estimated price


class VoiceErrorMessage(WireModel):
    type: Literal["error"] = "error"
    message: str


VoiceServerMessage = Annotated[
    Union[
        ReadyMessage,
        TranscriptMessage,
        AgentTextMessage,
        AgentToolMessage,
        AgentAudioStartMessage,
        AgentAudioEndMessage,
        AgentDoneMessage,
        VoiceErrorMessage,
    ],
    Field(discriminator="type"),
]
