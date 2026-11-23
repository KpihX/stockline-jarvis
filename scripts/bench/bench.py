#!/usr/bin/env python3
"""
Voice scenario bench: a synthetic caller (ElevenLabs via the ai service) replayed over WS /voice in real time.

    uv run --with websockets scripts/bench/bench.py --label "baseline"
    uv run --with websockets scripts/bench/bench.py --label "V0 all" --noise 0.03 --only stock_beaufort,prix_comte

Per scenario: caller mp3 (POST /tts, cached in scripts/bench/audio/) → ffmpeg → webm/opus (optional pink noise) →
audio_start, binary frames every 100 ms at real-time pace, audio_end (= t0, the "key release") → record what the
server reports (agent_done.timings / cost) and what the client sees (first agent audio byte after t0).
Prints a markdown table (median + worst case) and appends it to scripts/bench/results.md.

Cost: one real LLM turn + a few TTS sentences per scenario. Some scenarios may create a DRAFT order → run `make reset` after.
Nothing here confirms an order (the callers never say "oui"); a scenario fails if the agent calls confirm_order.
"""

import argparse
import asyncio
import json
import math
import statistics
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

import websockets

HERE = Path(__file__).resolve().parent
AUDIO = HERE / "audio"
FRAME_S = 0.1  # the browser's MediaRecorder.start(100)

# id, what the caller says, tools that must appear (any of), tools that must NOT appear.
SCENARIOS = [
    ("stock_beaufort", "Bonjour, il vous reste du Beaufort d'alpage en stock ?", {"get_product_stock", "search"}, {"confirm_order"}),
    # no tool required: the catalogue prices are in the prompt (context/03-glossaire-produits.md), the model may answer straight away
    ("prix_comte", "C'est combien le kilo de comté dix-huit mois, s'il vous plaît ?", set(), {"confirm_order"}),
    ("surnom_patates", "Il me faudrait des patates à tartiflette, vous en avez en ce moment ?", {"get_product_stock", "search"}, {"confirm_order"}),
    ("ambigu_reblochon", "Vous avez du reblochon en stock ?", {"get_product_stock", "search"}, {"confirm_order"}),
    (
        "dhab_sans_confirmer",
        "Bonjour, ici le Chalet du Recoin. Je voudrais la même chose que d'habitude pour demain.",
        {"search", "get_client", "get_client_history"},
        {"confirm_order"},
    ),
    (
        "client_bloque_commande",
        "Bonjour, ici la Bergerie des Deux Alpes. Je voudrais commander dix kilos de diots pour jeudi.",
        {"search", "get_client"},
        {"confirm_order"},
    ),
]


def post_tts(ai: str, text: str) -> bytes:
    req = urllib.request.Request(f"{ai}/tts", data=json.dumps({"text": text}).encode(), headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True
    )
    return float(out.stdout.strip())


def caller_webm(ai: str, sid: str, text: str, noise: float) -> tuple[bytes, float]:
    """mp3 (cached) → webm/opus with 300 ms of lead-in, 300 ms of tail, optional pink noise."""
    AUDIO.mkdir(exist_ok=True)
    mp3 = AUDIO / f"{sid}.mp3"
    if not mp3.exists():
        mp3.write_bytes(post_tts(ai, text))
    out = AUDIO / f"{sid}.{'noise%g' % noise if noise else 'clean'}.webm"
    if not out.exists():
        graph = "[0:a]adelay=300:all=1,apad=pad_dur=0.3[s]"
        if noise:
            graph += f";anoisesrc=color=pink:amplitude={noise}:sample_rate=44100[n];[s][n]amix=inputs=2:duration=first:normalize=0[o]"
        else:
            graph += ";[s]anull[o]"
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-i", str(mp3), "-filter_complex", graph, "-map", "[o]", "-ac", "1", "-ar", "48000", "-c:a", "libopus", "-b:a", "32k", "-f", "webm", str(out)],
            check=True,
        )
    return out.read_bytes(), duration(out)


async def recv(ws, timeout: float):
    return await asyncio.wait_for(ws.recv(), timeout)


async def run_scenario(ws_url: str, sid: str, webm: bytes, dur: float, expect: set, forbid: set, settle: float, timeout: float) -> dict:
    async with websockets.connect(ws_url, max_size=None) as ws:
        await ws.send(json.dumps({"type": "start", "actorName": "Agent vocal"}))
        ready = {}
        while ready.get("type") != "ready":  # (ignore anything else, e.g. a warm-up error)
            m = await recv(ws, 15)
            ready = json.loads(m) if isinstance(m, str) else {}
        await asyncio.sleep(settle)  # a person needs a moment to press the key

        await ws.send(json.dumps({"type": "audio_start", "mime": "audio/webm;codecs=opus"}))
        n = max(1, math.ceil(dur / FRAME_S))
        size = math.ceil(len(webm) / n)
        t_begin = time.perf_counter()
        for i in range(n):
            await ws.send(webm[i * size : (i + 1) * size])
            await asyncio.sleep(max(0.0, t_begin + (i + 1) * FRAME_S - time.perf_counter()))
        await ws.send(json.dumps({"type": "audio_end"}))
        t0 = time.perf_counter()  # key release

        res: dict = {"transcript": "", "tools": [], "text": "", "error": None, "clientFirstAudioMs": None, "done": None}
        audio_bytes, agent_audio = 0, bytearray()
        try:
            while True:
                m = await recv(ws, timeout)
                if isinstance(m, bytes):
                    audio_bytes += len(m)
                    agent_audio += m
                    if res["clientFirstAudioMs"] is None:
                        res["clientFirstAudioMs"] = round((time.perf_counter() - t0) * 1000)
                    continue
                msg = json.loads(m)
                match msg["type"]:
                    case "transcript" if msg.get("final"):
                        res["transcript"] = msg["text"]
                    case "agent_tool" if msg.get("ok") is None:
                        res["tools"].append(msg["name"])
                    case "error":
                        res["error"] = msg["message"]
                        break
                    case "agent_done":
                        res["done"], res["text"] = msg, msg["text"]
                        break
        except TimeoutError:
            res["error"] = f"timeout {timeout}s"
    d = res["done"] or {}
    timings, cost = d.get("timings") or {}, d.get("cost") or {}
    res.update({k: timings.get(k) for k in ("sttMs", "llmFirstTokenMs", "llmTotalMs", "ttsFirstByteMs", "totalMs", "answerMs", "firstSoundKind")})
    res["cost"] = cost
    # a filler and the answer arrive as ONE audio segment: the bench cannot tell them apart, only the server's answerMs can
    res["agentAudio"] = bytes(agent_audio)
    res["ok"] = bool(
        not res["error"] and audio_bytes and res["transcript"] and (not expect or expect & set(res["tools"])) and not (forbid & set(res["tools"]))
    )
    res["ready"] = ready
    return res


def med(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def worst(xs):
    xs = [x for x in xs if x is not None]
    return max(xs) if xs else None


def fmt(x, nd=0):
    return "—" if x is None else (f"{x:.{nd}f}" if nd else f"{round(x)}")


def report(label: str, noise: float, results: list[tuple[str, dict]]) -> str:
    ready = results[0][1].get("ready", {}) if results else {}
    kinds = [r.get("firstSoundKind") for _, r in results]
    lines = [
        f"## {label}",
        f"_{datetime.now():%Y-%m-%d %H:%M}_ · llm `{ready.get('llm')}` · stt `{ready.get('stt')}` · tts `{ready.get('tts')}` · noise {noise or 'none'} · "
        f"t0 = audio_end sent (key release) · `clientFirstAudioMs` = t0 → first binary agent frame seen by the bench · "
        f"`answerMs` = t0 → first byte of the real answer (server; = totalMs when no filler)",
        "",
        "| scenario | ok | sttMs | llm1stMs | llmTotMs | ttsFirstMs | totalMs | answerMs | clientFirstMs | 1st sound | in/out/cacheR/cacheW tok | STT s | TTS chars | € | tools |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for sid, r in results:
        c = r.get("cost") or {}
        toks = "/".join(fmt(c.get(k)) for k in ("llmInputTokens", "llmOutputTokens", "llmCacheReadTokens", "llmCacheCreationTokens"))
        lines.append(
            f"| {sid} | {'✅' if r['ok'] else '❌ ' + str(r['error'] or '')} | {fmt(r['sttMs'])} | {fmt(r['llmFirstTokenMs'])} | {fmt(r['llmTotalMs'])} | "
            f"{fmt(r['ttsFirstByteMs'])} | {fmt(r['totalMs'])} | {fmt(r.get('answerMs'))} | {fmt(r['clientFirstAudioMs'])} | {r.get('firstSoundKind') or '—'} | "
            f"{toks} | {fmt(c.get('sttSeconds'), 1)} | {fmt(c.get('ttsChars'))} | {fmt(c.get('estimatedEur'), 4)} | {','.join(r['tools'])} |"
        )
    rs = [r for _, r in results]
    passed = sum(r["ok"] for r in rs)
    for name, fn in (("median", med), ("worst", worst)):
        lines.append(
            f"| **{name}** | {passed}/{len(rs)} | " + " | ".join(fmt(fn([r.get(k) for r in rs])) for k in ("sttMs", "llmFirstTokenMs", "llmTotalMs", "ttsFirstByteMs", "totalMs", "answerMs", "clientFirstAudioMs"))
            + f" | {'/'.join(sorted({str(k) for k in kinds}))} | | | | {fmt(fn([(r.get('cost') or {}).get('estimatedEur') for r in rs]), 4)} | |"
        )
    lines += ["", "Transcripts (what the STT heard) and answers:", ""]
    for sid, r in results:
        lines.append(f"- `{sid}`: « {r['transcript']} » → « {r['text'].strip()} »")
    return "\n".join(lines) + "\n"


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--label", required=True, help="what is being measured (e.g. 'baseline', 'V0.2 filler')")
    ap.add_argument("--ai", default="http://localhost:4100")
    ap.add_argument("--only", default="", help="comma-separated scenario ids")
    ap.add_argument("--noise", type=float, default=0.0, help="pink noise amplitude mixed under the caller (0 = none, 0.03 ≈ busy kitchen)")
    ap.add_argument("--settle", type=float, default=1.0, help="seconds between `ready` and the first audio frame")
    ap.add_argument("--timeout", type=float, default=60.0, help="max wait for agent_done after the release")
    ap.add_argument("--out", default=str(HERE / "results.md"))
    ap.add_argument("--no-write", action="store_true", help="print only, do not append to results.md")
    ap.add_argument("--save-agent-audio", action="store_true", help="keep the agent's audio in scripts/bench/audio/out/<scenario>.mp3")
    args = ap.parse_args()

    wanted = set(filter(None, args.only.split(",")))
    ws_url = args.ai.replace("http", "ws", 1) + "/voice"
    results = []
    for sid, text, expect, forbid in SCENARIOS:
        if wanted and sid not in wanted:
            continue
        webm, dur = caller_webm(args.ai, sid, text, args.noise)
        print(f"▶ {sid} ({dur:.1f}s) …", file=sys.stderr, flush=True)
        r = await run_scenario(ws_url, sid, webm, dur, expect, forbid, args.settle, args.timeout)
        print(f"  {'ok' if r['ok'] else 'FAIL'} total={r['totalMs']} tools={r['tools']} {r['error'] or ''}", file=sys.stderr, flush=True)
        if args.save_agent_audio:  # listen to what the agent said (filler + answer = one mp3 stream)
            (AUDIO / "out").mkdir(parents=True, exist_ok=True)
            (AUDIO / "out" / f"{sid}.mp3").write_bytes(r["agentAudio"])
        results.append((sid, r))
    if not results:
        print("no scenario selected", file=sys.stderr)
        return 1
    md = report(args.label, args.noise, results)
    print(md)
    if not args.no_write:
        with open(args.out, "a", encoding="utf-8") as f:
            f.write(md + "\n")
    return 0 if all(r["ok"] for _, r in results) else 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
