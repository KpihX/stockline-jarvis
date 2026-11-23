"""
NVIDIA STT over Riva gRPC, hosted on NVCF (grpc.nvcf.nvidia.com:443). OPTIONAL provider: STT_PROVIDER=nvidia.

Two NVCF functions, picked with STT_MODEL (or NVIDIA_STT_FUNCTION_ID for any other Riva function):

    parakeet-1.1b-rnnt-multilingual   streaming (interim results while the caller speaks) + word boosting
    whisper-large-v3                  offline only (the Riva Whisper model does not stream, nor take word boosting)

    streams     True for Parakeet (NVIDIA_STT_STREAMING=auto|on|off): audio goes to Riva as it is recorded, so only
                the tail is left at the key release. Whisper: one blocking call on the whole recording, run in a thread.
    vocabulary  the `hint` terms (client / product names) become a Riva speech context, ONE boost score for all
                (NVIDIA_STT_BOOST; RNNT/TDT range documented as 0.5-2.0; 0 = off). Whisper ignores it, so it is not sent.
                A function that rejects the context (INVALID_ARGUMENT / UNIMPLEMENTED) switches boosting off for the
                life of the process and the call is repeated without it.
    audio       Riva wants PCM: WAV (16 kHz mono 16-bit) is unwrapped in pure Python; anything else (the browser's
                WebM/Opus, Safari's mp4) is decoded by an `ffmpeg` subprocess (pipe in, s16le 16 kHz out).
    language    Parakeet needs a locale ("fr-FR") or "multi", never "fr": STT_LANGUAGE=fr is mapped to fr-FR.

`nvidia-riva-client` is imported lazily (uv sync --extra nvidia): without it, or without the key, every other provider
is unaffected and this one answers with a clear ProviderError.
"""

import asyncio
import queue
import shutil
import struct
import threading
from collections.abc import AsyncIterator
from typing import Any

from .base import STTClient, STTUpdate
from .http import ProviderError, provider_error

URI = "grpc.nvcf.nvidia.com:443"
# alias → (NVCF function id, streams, takes word boosting). Function ids are public identifiers, not secrets.
MODELS = {
    "parakeet-1.1b-rnnt-multilingual": ("71203149-d3b7-4460-8231-1be2543a1fca", True, True),
    "whisper-large-v3": ("b702f636-f60c-4a3d-a6f4-f3568c13bd7d", False, False),
}
ALIASES = {"parakeet": "parakeet-1.1b-rnnt-multilingual", "whisper": "whisper-large-v3"}
LOCALES = {"fr": "fr-FR", "en": "en-US", "es": "es-US", "de": "de-DE", "it": "it-IT", "pt": "pt-BR"}  # Parakeet rejects bare codes
DEFAULT_BOOST = 1.0  # RNNT/TDT scale (0.5-2.0); the CTC scale (20-100) is NOT valid here
MAX_BOOST_TERMS = 500  # per-stream boosting is advised up to ~500 words on RNNT
SAMPLE_RATE = 16000
CHUNK = 3200  # 100 ms of 16 kHz mono s16le
WHO = "nvidia stt"
# small probe: the decoder must start on the first frames of a live recording, not after 5 s of audio
FFMPEG = ["ffmpeg", "-v", "error", "-nostdin", "-probesize", "4096", "-analyzeduration", "0", "-i", "pipe:0"]
FFMPEG += ["-f", "s16le", "-ar", str(SAMPLE_RATE), "-ac", "1", "pipe:1"]
_DONE = object()


def model_alias(model: str) -> str:
    low = model.lower()
    return next((full for key, full in ALIASES.items() if low.startswith(key)), low)


def boost_terms(hint: str | None) -> list[str]:
    """The hint's comma-separated terms, deduplicated, first ones first (the most misheard come first)."""
    seen, out = set(), []
    for t in (t.strip() for t in (hint or "").split(",")):
        if t and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out[:MAX_BOOST_TERMS]


# ── audio → PCM ──


class AudioFormatError(ProviderError):
    pass


def wav_data_offset(head: bytes) -> int | None:
    """Offset of the PCM samples in a WAV header, once `head` holds all of it up to the "data" chunk; None = need more.
    Raises AudioFormatError unless the file is 16 kHz mono 16-bit PCM."""
    pos, fmt = 12, None
    while pos + 8 <= len(head):
        cid, size = head[pos : pos + 4], struct.unpack("<I", head[pos + 4 : pos + 8])[0]
        if cid == b"fmt " and pos + 8 + 16 <= len(head):
            fmt = struct.unpack("<HHIIHH", head[pos + 8 : pos + 24])  # tag, channels, rate, byte rate, align, bits
        if cid == b"data":
            if fmt is None:
                raise AudioFormatError("wav without a fmt chunk")
            if (fmt[0], fmt[1], fmt[2], fmt[5]) != (1, 1, SAMPLE_RATE, 16):
                raise AudioFormatError(
                    f"{WHO}: WAV must be 16 kHz mono 16-bit PCM (got {fmt[1]} ch, {fmt[2]} Hz, {fmt[5]} bit): "
                    "convert it, or send WebM (decoded by ffmpeg)"
                )
            return pos + 8
        pos += 8 + size + (size & 1)
    return None


async def regroup(chunks: AsyncIterator[bytes], size: int = CHUNK) -> AsyncIterator[bytes]:
    """Re-cut a byte stream in `size` pieces (a short last piece is kept)."""
    buf = b""
    async for c in chunks:
        buf += c
        while len(buf) >= size:
            yield buf[:size]
            buf = buf[size:]
    if buf:
        yield buf


async def wav_pcm(audio: AsyncIterator[bytes], first: bytes) -> AsyncIterator[bytes]:
    head, offset = first, wav_data_offset(first)
    if offset is None:  # the header spans several chunks
        async for c in audio:
            head += c
            if (offset := wav_data_offset(head)) is not None:
                break
    if offset is None:
        raise AudioFormatError(f"{WHO}: truncated WAV header")

    async def body() -> AsyncIterator[bytes]:
        yield head[offset:]
        async for c in audio:
            yield c

    async for piece in regroup(body()):
        yield piece


async def ffmpeg_pcm(audio: AsyncIterator[bytes], first: bytes) -> AsyncIterator[bytes]:
    """Decode any container ffmpeg knows (browser WebM/Opus, mp4…) while it arrives."""
    if not shutil.which("ffmpeg"):
        raise AudioFormatError(f"{WHO}: ffmpeg is needed to decode the browser's WebM/Opus audio (or send 16 kHz mono WAV); install ffmpeg")
    proc = await asyncio.create_subprocess_exec(
        *FFMPEG, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    assert proc.stdin and proc.stdout

    async def feed() -> None:
        try:
            proc.stdin.write(first)
            async for c in audio:
                proc.stdin.write(c)
                await proc.stdin.drain()
            await proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            pass  # ffmpeg quit: its stderr says why
        finally:
            proc.stdin.close()

    feeder = asyncio.create_task(feed())
    try:
        async for piece in regroup(_read(proc.stdout)):
            yield piece
        await feeder
        if await proc.wait():
            err = (await proc.stderr.read()).decode("utf-8", "replace")[:200] if proc.stderr else ""
            raise AudioFormatError(f"{WHO}: ffmpeg could not decode the audio: {err}")
    finally:
        feeder.cancel()
        if proc.returncode is None:
            proc.kill()
            await proc.wait()


async def _read(stream: asyncio.StreamReader) -> AsyncIterator[bytes]:
    while chunk := await stream.read(CHUNK):
        yield chunk


async def pcm_chunks(audio: AsyncIterator[bytes], mime: str) -> AsyncIterator[bytes]:
    """Audio in any supported container → 16 kHz mono s16le in 100 ms pieces (sniffs the first bytes, not just `mime`)."""
    first = b""
    async for c in audio:
        if c:
            first = c
            break
    if not first:
        return
    decoder = wav_pcm if first[:4] == b"RIFF" else ffmpeg_pcm
    async for piece in decoder(audio, first):
        yield piece


# ── the provider ──


class NvidiaSTT(STTClient):
    name = "nvidia"

    def __init__(
        self,
        api_key: str,
        model: str = "parakeet-1.1b-rnnt-multilingual",
        language: str = "fr",
        *,
        function_id: str = "",
        uri: str = "",
        boost: float | None = None,
        streaming: str = "auto",
        riva: Any = None,
    ):
        """`riva`: the `riva.client` module (tests inject a fake; None = import it on first use)."""
        self.model = model_alias(model)
        known = MODELS.get(self.model)
        self.function_id = function_id or (known[0] if known else "")
        if not self.function_id:
            raise ValueError(f"unknown NVIDIA STT model '{model}': known {', '.join(MODELS)}, or set NVIDIA_STT_FUNCTION_ID")
        takes_boost = known[2] if known else True
        self.boost = (DEFAULT_BOOST if takes_boost else 0.0) if boost is None else boost
        streams = known[1] if known else False
        self.streams = {"on": True, "off": False}.get(streaming.lower(), streams)
        self.api_key, self.uri, self._riva, self._asr = api_key, uri or URI, riva, None
        bare = "-" not in language and language.lower() != "multi" and self.model.startswith("parakeet")
        self.language = LOCALES.get(language.lower(), language) if bare else language  # Parakeet: "fr" → "fr-FR"

    # riva plumbing -----------------------------------------------------------------------------------------------

    def riva(self) -> Any:
        if self._riva is None:
            try:
                import riva.client as rc
            except ImportError:
                raise ProviderError(
                    f"{WHO}: nvidia-riva-client is not installed — `cd apps/ai && uv sync --extra nvidia` (Docker: see README, STT section)"
                ) from None
            self._riva = rc
        return self._riva

    def asr(self) -> Any:
        """One gRPC channel for the process (HTTP/2 multiplexes the calls: no TLS handshake per utterance)."""
        if self._asr is None:
            rc = self.riva()
            auth = rc.Auth(
                use_ssl=True,
                uri=self.uri,
                metadata_args=[["function-id", self.function_id], ["authorization", f"Bearer {self.api_key}"]],
            )
            self._asr = rc.ASRService(auth)
        return self._asr

    def config(self, hint: str | None, interim: bool):
        rc = self.riva()
        cfg = rc.RecognitionConfig(
            encoding=rc.AudioEncoding.LINEAR_PCM,
            sample_rate_hertz=SAMPLE_RATE,
            audio_channel_count=1,
            language_code=self.language,
            max_alternatives=1,
            enable_automatic_punctuation=True,
        )
        terms = boost_terms(hint) if self.boost > 0 else []
        if terms:
            rc.add_word_boosting_to_config(cfg, terms, self.boost)
        return rc.StreamingRecognitionConfig(config=cfg, interim_results=True) if interim else cfg

    def error(self, e: Exception) -> Exception:
        """grpc.RpcError → the kit's ProviderError (HTTP-like status so the UI hint for keys / quota applies)."""
        if isinstance(e, ProviderError):
            return e
        code = getattr(e, "code", None)
        if not callable(code):
            return provider_error(WHO, type(e).__name__, str(e))
        name = code().name
        status = {"UNAUTHENTICATED": 401, "PERMISSION_DENIED": 403, "RESOURCE_EXHAUSTED": 429}.get(name, name)
        return provider_error(WHO, status, str(e.details() if hasattr(e, "details") else e))

    def boost_rejected(self, e: Exception) -> bool:
        """The function refused the speech context: stop sending one (the caller repeats without)."""
        code = getattr(e, "code", None)
        if self.boost > 0 and callable(code) and code().name in ("INVALID_ARGUMENT", "UNIMPLEMENTED"):
            print(f"[ai] nvidia stt: word boosting rejected by the function ({code().name}), disabled", flush=True)
            self.boost = 0.0
            return True
        return False

    # batch -------------------------------------------------------------------------------------------------------

    def recognize(self, pcm: bytes, hint: str | None) -> str:
        """Blocking Riva call: run it in a thread."""
        response = self.asr().offline_recognize(pcm, self.config(hint, interim=False))
        parts = [alt.transcript.strip() for res in response.results for alt in list(res.alternatives)[:1]]
        return " ".join(p for p in parts if p)

    async def transcribe(self, audio: bytes, mime: str, hint: str | None = None) -> str:
        async def one() -> AsyncIterator[bytes]:
            yield audio

        pcm = b"".join([c async for c in pcm_chunks(one(), mime)])
        if not pcm:
            return ""
        for attempt in (1, 2):
            try:
                return await asyncio.to_thread(self.recognize, pcm, hint)
            except Exception as e:
                if attempt == 1 and self.boost_rejected(e):
                    continue
                raise self.error(e) from None
        return ""

    # live --------------------------------------------------------------------------------------------------------

    async def transcribe_stream(self, audio: AsyncIterator[bytes], mime: str, hint: str | None = None) -> AsyncIterator[STTUpdate]:
        if not self.streams:  # Whisper: wait for the end of the audio, one call
            async for update in super().transcribe_stream(audio, mime, hint):
                yield update
            return
        asr, config = self.asr(), self.config(hint, interim=True)
        loop = asyncio.get_running_loop()
        inbox: queue.Queue[bytes | None] = queue.Queue()  # PCM for the gRPC thread, None = end of audio
        outbox: asyncio.Queue[Any] = asyncio.Queue()  # Riva responses (or an exception, or _DONE) for this coroutine

        def worker() -> None:
            try:
                for response in asr.streaming_response_generator(iter(inbox.get, None), config):
                    loop.call_soon_threadsafe(outbox.put_nowait, response)
                loop.call_soon_threadsafe(outbox.put_nowait, _DONE)
            except Exception as e:  # noqa: BLE001 — handed over to the event loop
                loop.call_soon_threadsafe(outbox.put_nowait, e)

        async def pump() -> None:
            try:
                async for piece in pcm_chunks(audio, mime):
                    inbox.put(piece)
            except Exception as e:  # noqa: BLE001 — audio source / decoder failure
                outbox.put_nowait(e)
            finally:
                inbox.put(None)

        threading.Thread(target=worker, daemon=True, name="nvidia-stt").start()
        pumping = asyncio.create_task(pump())
        final = ""  # final segments, each sent once
        try:
            while (item := await outbox.get()) is not _DONE:
                if isinstance(item, Exception):
                    if not final and self.boost_rejected(item):
                        raise ProviderError(f"{WHO}: word boosting rejected, transcribing the whole recording instead") from None
                    raise self.error(item) from None
                interim = ""
                for res in item.results:
                    text = (res.alternatives[0].transcript if res.alternatives else "").strip()
                    if not text:
                        continue
                    if res.is_final:
                        final = f"{final} {text}".strip()
                    else:
                        interim = text
                yield STTUpdate(f"{final} {interim}".strip(), stable=final)
            yield STTUpdate(final, final=True, stable=final)
        finally:
            pumping.cancel()
            inbox.put(None)  # barge-in / client gone: end the request stream so the gRPC thread finishes by itself
