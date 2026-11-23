"""
NVIDIA STT (Riva gRPC on NVCF), tested offline: `riva.client` is replaced by a fake module (injected through
`NvidiaSTT(riva=…)`), like Soniox's `connect`. No key, no network, nvidia-riva-client not even needed.
"""

import io
import sys
import wave
from types import SimpleNamespace as NS

import pytest

from app.clients.base import STTUpdate
from app.clients.factory import ConfigError, make_stt_client
from app.clients.http import ProviderError
from app.clients.nvidia import AudioFormatError, NvidiaSTT, boost_terms, model_alias, pcm_chunks, wav_data_offset
from app.clients.ws import once
from app.config import STTSettings

PCM = bytes(range(256)) * 50  # 12 800 bytes = 400 ms of fake 16 kHz s16le


def wav(pcm: bytes = PCM, rate: int = 16000, channels: int = 1) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def result(text: str, final: bool):
    return NS(alternatives=[NS(transcript=text)], is_final=final)


class RpcError(Exception):
    """What grpc raises: code() returns an enum-like with .name, details() the server's message."""

    def __init__(self, name: str, details: str = "boom"):
        super().__init__(details)
        self._name, self._details = name, details

    def code(self):
        return NS(name=self._name)

    def details(self):
        return self._details


class FakeRiva:
    """Stands in for the `riva.client` module and records what the adapter asks of it."""

    AudioEncoding = NS(LINEAR_PCM="PCM")

    def __init__(self, offline=None, stream=None):
        self.offline, self.stream = offline or [], stream  # offline: results per call (or an exception to raise)
        self.auth_args, self.calls, self.boosts, self.pcm = None, [], [], []

    def Auth(self, **kw):  # noqa: N802 — mirrors the riva API
        self.auth_args = kw
        return NS(channel=None)

    def RecognitionConfig(self, **kw):  # noqa: N802
        return NS(**kw, boosted=None)

    def StreamingRecognitionConfig(self, config, interim_results):  # noqa: N802
        return NS(config=config, interim_results=interim_results)

    def add_word_boosting_to_config(self, config, words, score):
        config.boosted = (words, score)
        self.boosts.append((words, score))

    def ASRService(self, auth):  # noqa: N802
        riva = self

        class Service:
            def offline_recognize(self, audio, config):
                riva.calls.append(config)
                riva.pcm.append(audio)
                step = riva.offline.pop(0)
                if isinstance(step, Exception):
                    raise step
                return NS(results=[NS(alternatives=[NS(transcript=t)]) for t in step])

            def streaming_response_generator(self, chunks, config):
                riva.calls.append(config)
                yield from riva.stream(chunks, config)

        return Service()


def make(riva, model="parakeet", **kw):
    return NvidiaSTT("k", model, kw.pop("language", "fr"), riva=riva, **kw)


# ── configuration ──


def test_models_languages_and_boost_defaults():
    p, w = make(FakeRiva()), make(FakeRiva(), "whisper-large-v3")
    assert (p.model, p.language, p.streams, p.boost) == ("parakeet-1.1b-rnnt-multilingual", "fr-FR", True, 1.0)
    assert (w.model, w.language, w.streams, w.boost) == ("whisper-large-v3", "fr", False, 0.0)  # whisper: no streaming, no boosting
    assert make(FakeRiva(), language="multi").language == "multi"
    assert make(FakeRiva(), language="fr-CA").language == "fr-CA"
    assert make(FakeRiva(), boost=0.5, streaming="off").streams is False and make(FakeRiva(), "whisper", streaming="on").streams is True
    assert make(FakeRiva(), "whisper", boost=2.0).boost == 2.0  # forcing it is allowed (benchmark: does whisper ignore it?)
    assert model_alias("Parakeet-whatever") == "parakeet-1.1b-rnnt-multilingual"
    with pytest.raises(ValueError, match="NVIDIA_STT_FUNCTION_ID"):
        make(FakeRiva(), "some-other-model")
    assert make(FakeRiva(), "some-other-model", function_id="abc").function_id == "abc"


def test_boost_terms_dedupe_and_cap():
    assert boost_terms(" Lemoine, loup ,lemoine,, bar ") == ["Lemoine", "loup", "bar"]
    assert boost_terms(None) == [] and len(boost_terms(",".join(f"t{i}" for i in range(900)))) == 500


def test_factory_builds_nvidia_and_degrades_to_clear_errors():
    def cfg(api_key="", model="", **kw):
        return STTSettings(provider="nvidia", api_key=api_key, model=model, language="fr", mock_text="", **kw)

    stt = make_stt_client(cfg(nvidia_api_key="nk"))
    assert (type(stt).__name__, stt.name, stt.model, stt.api_key, stt.streams) == (
        "NvidiaSTT",
        "nvidia",
        "parakeet-1.1b-rnnt-multilingual",
        "nk",
        True,
    )
    assert make_stt_client(cfg(api_key="sk")).api_key == "sk"  # STT_API_KEY is accepted too
    assert make_stt_client(cfg(nvidia_api_key="nk", api_key="sk")).api_key == "nk"  # NVIDIA_API_KEY wins
    assert make_stt_client(cfg(nvidia_api_key="nk", model="whisper")).streams is False
    assert make_stt_client(cfg(nvidia_api_key="nk", nvidia_streaming="off")).streams is False
    with pytest.raises(ConfigError, match="NVIDIA_API_KEY"):
        make_stt_client(cfg())
    with pytest.raises(ConfigError, match="NVIDIA_STT_FUNCTION_ID"):
        make_stt_client(cfg(nvidia_api_key="nk", model="nope"))


async def test_missing_riva_package_is_a_provider_error_not_a_crash(monkeypatch):
    monkeypatch.setitem(sys.modules, "riva.client", None)  # `import riva.client` → ImportError
    stt = NvidiaSTT("k")  # building it never imports riva
    with pytest.raises(ProviderError, match="uv sync --extra nvidia"):
        await stt.transcribe(wav(), "audio/wav")


# ── audio → PCM ──


async def test_wav_is_unwrapped_to_pcm_chunks_of_100ms():
    chunks = [c async for c in pcm_chunks(once(*[wav()[i : i + 1000] for i in range(0, len(wav()), 1000)]), "audio/wav")]
    assert b"".join(chunks) == PCM and all(len(c) == 3200 for c in chunks[:-1])


def test_wav_must_be_16k_mono():
    assert wav_data_offset(wav()[:20]) is None  # header not complete yet
    assert wav_data_offset(wav()) == 44
    with pytest.raises(AudioFormatError, match="16 kHz mono"):
        wav_data_offset(wav(rate=44100))
    with pytest.raises(AudioFormatError, match="16 kHz mono"):
        wav_data_offset(wav(channels=2))


async def test_other_containers_need_ffmpeg(monkeypatch):
    monkeypatch.setattr("app.clients.nvidia.shutil.which", lambda _: None)
    with pytest.raises(AudioFormatError, match="ffmpeg"):
        [c async for c in pcm_chunks(once(b"\x1a\x45\xdf\xa3webm"), "audio/webm;codecs=opus")]


# ── batch ──


async def test_batch_sends_raw_pcm_language_and_the_vocabulary_boost():
    riva = FakeRiva(offline=[["Bonjour,", "il reste du bar ?"]])
    text = await make(riva).transcribe(wav(), "audio/wav", "Lemoine, loup")
    cfg = riva.calls[0]
    assert text == "Bonjour, il reste du bar ?"
    assert riva.pcm == [PCM] and (cfg.language_code, cfg.sample_rate_hertz, cfg.encoding) == ("fr-FR", 16000, "PCM")
    assert cfg.boosted == (["Lemoine", "loup"], 1.0)
    assert riva.auth_args["uri"] == "grpc.nvcf.nvidia.com:443" and riva.auth_args["use_ssl"] is True
    assert ["function-id", "71203149-d3b7-4460-8231-1be2543a1fca"] in riva.auth_args["metadata_args"]
    assert ["authorization", "Bearer k"] in riva.auth_args["metadata_args"]


async def test_whisper_gets_no_vocabulary_and_empty_audio_makes_no_call():
    riva = FakeRiva(offline=[["ok"]])
    stt = make(riva, "whisper-large-v3")
    assert await stt.transcribe(wav(), "audio/wav", "Lemoine") == "ok" and riva.boosts == [] and riva.calls[0].language_code == "fr"
    assert await stt.transcribe(b"", "audio/wav") == "" and len(riva.calls) == 1


async def test_rejected_boosting_is_switched_off_and_the_call_repeated():
    riva = FakeRiva(offline=[RpcError("INVALID_ARGUMENT", "speech_contexts unsupported"), ["salut"], ["encore"]])
    stt = make(riva)
    assert await stt.transcribe(wav(), "audio/wav", "Lemoine") == "salut"
    assert stt.boost == 0.0 and riva.calls[0].boosted is not None and riva.calls[1].boosted is None
    assert await stt.transcribe(wav(), "audio/wav", "Lemoine") == "encore" and len(riva.boosts) == 1  # never boosted again


@pytest.mark.parametrize("code,status", [("UNAUTHENTICATED", "401"), ("RESOURCE_EXHAUSTED", "429"), ("UNAVAILABLE", "UNAVAILABLE")])
async def test_grpc_errors_become_provider_errors_with_the_kits_hints(code, status):
    stt = make(FakeRiva(offline=[RpcError(code, "nope")]), boost=0)
    with pytest.raises(ProviderError, match=f"nvidia stt HTTP {status}: nope") as e:
        await stt.transcribe(wav(), "audio/wav")
    if status != "UNAVAILABLE":
        assert "STT_API_KEY" in str(e.value) or "quota" in str(e.value)


# ── live ──


def fake_stream(chunks, config):
    """Riva streaming: an interim result per 3 chunks, a final one per 6, the rest final at the end of the audio."""
    seen = 0
    for _ in chunks:
        seen += 1
        if seen == 3:
            yield NS(results=[result("bonjour il", False)])
        if seen == 6:
            yield NS(results=[result("Bonjour, il", True)])
        if seen == 8:
            yield NS(results=[result("reste du", False)])
    yield NS(results=[result("reste du bar ?", True)])  # sent when the audio ends


async def test_streaming_gives_partials_then_the_final_text():
    riva = FakeRiva(stream=fake_stream)
    stt = make(riva)
    audio = wav(PCM * 4)  # 1.6 s = 16 chunks of 100 ms
    updates = [u async for u in stt.transcribe_stream(once(audio), "audio/wav", "Lemoine")]
    assert updates[0] == STTUpdate("bonjour il", stable="")
    assert STTUpdate("Bonjour, il reste du", stable="Bonjour, il") in updates
    assert updates[-1] == STTUpdate("Bonjour, il reste du bar ?", final=True, stable="Bonjour, il reste du bar ?")
    assert riva.calls[0].interim_results is True and riva.calls[0].config.boosted == (["Lemoine"], 1.0)


async def test_streaming_error_surfaces_as_provider_error_and_disables_rejected_boosting():
    def broken(chunks, config):
        list(chunks)
        raise RpcError("INVALID_ARGUMENT", "speech context")
        yield  # pragma: no cover

    stt = make(FakeRiva(stream=broken))
    with pytest.raises(ProviderError, match="boosting rejected"):  # utterance.py then transcribes the whole recording
        [u async for u in stt.transcribe_stream(once(wav()), "audio/wav", "Lemoine")]
    assert stt.boost == 0.0

    stt = make(FakeRiva(stream=broken), boost=0)
    with pytest.raises(ProviderError, match="INVALID_ARGUMENT"):
        [u async for u in stt.transcribe_stream(once(wav()), "audio/wav")]


async def test_a_non_streaming_model_waits_for_the_end_then_one_final_update():
    riva = FakeRiva(offline=[["Il reste du bar ?"]])
    updates = [u async for u in make(riva, "whisper").transcribe_stream(once(wav()), "audio/wav")]
    assert updates == [STTUpdate("Il reste du bar ?", final=True, stable="Il reste du bar ?")]
