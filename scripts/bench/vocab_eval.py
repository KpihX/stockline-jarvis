"""
Offline evaluation of the vocabulary resolver on STORED transcripts (no STT / LLM / TTS call, no quota).

    cd apps/ai && uv run python ../../scripts/bench/vocab_eval.py            # ERP must answer on ERP_API_URL (default http://localhost:4000)

Inputs (git-ignored lab folder): tmp/stt-lab/{corpus.py, score.py, results/soniox.json, results/nvidia.json}: 20 real sentences,
62 entity words, and what each engine (soniox-plain, soniox-vocab, whisper-v3, parakeet) transcribed.
The ERP is only READ (products, clients, one client sheet per sentence).

What it prints, per engine:
  recall      entity words heard right: raw  →  with the resolver's confident proposals  →  also counting ambiguous candidates (the agent would ask)
  A / B / C   A = global lexicon only · B = + client lexicon (contacts, places, usual products) · C = B + lessons learned from earlier confirmed calls
              (C replays each correct proposal as if the caller had confirmed it in a previous call: an upper bound for repeat mistakes)
  false pos.  proposals that are not a correction of a missed entity ("spurious"): on the 20 sentences and on 12 invented negative sentences
              (words that look like products or clients but are not). Spurious ambiguous mentions only cost one clarifying question.
  latency     resolver time per sentence (global + client indexes already built)
"""

import json
import os
import statistics
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
LAB = ROOT / "tmp" / "stt-lab"
sys.path.insert(0, str(LAB))
sys.path.insert(0, str(ROOT / "apps" / "ai"))

from corpus import CORPUS  # noqa: E402
from score import norm  # noqa: E402

from app.lexicon.catalogue import build_catalogue, build_client  # noqa: E402
from app.lexicon.learned import Learned  # noqa: E402
from app.lexicon.resolver import Index, resolve  # noqa: E402

ERP = os.environ.get("ERP_API_URL", "http://localhost:4000").rstrip("/")

# Invented sentences: nothing here is a product or a client, but several words sound like one.
NEGATIVES = [
    "Pouvez-vous me rappeler vers dix heures, j'ai un souci avec mon téléphone ?",
    "Mon camion est en panne sur la route du col du Lautaret, je serai en retard.",
    "Le comptable passe vendredi pour vérifier les plats du jour et la caisse.",
    "J'ai collé un magnet sur le frigo et une bavure sur la facture m'a étonné.",
    "Mon cousin Rémi vient m'aider samedi en salle pour le service du midi.",
    "On a eu un client très content, il a dit que la salle était magnifique.",
    "Il faudrait réparer la porte de la chambre froide avant la saison.",
    "Je voulais juste savoir si vous aviez reçu mon courrier de la semaine dernière.",
    "Le chef a une nouvelle recette avec des pommes, du miel et des noix, je vous raconterai.",
    "Notre salon de thé ouvre à la montagne en décembre, c'est un grand projet.",
    "Mon associé s'appelle Marc et il gère la terrasse, la cuisine et la plonge.",
    "Je suis au bout du fil depuis cinq minutes, pouvez-vous me passer le commercial ?",
]

# Invented AFTER the resolver was tuned, never looked at while tuning: plausible STT slips on catalogue items (hypothesis, expected entity words).
HELD_OUT = [
    ("du Bofort d'alpage pour demain", "beaufort d alpage"),
    ("des crozés au sarrasin", "crozets"),
    ("du saint Marcelain bien coulant", "marcellin"),
    ("une raclète tranchée", "raclette tranchee"),
    ("Ici la fondue de Taillefère", "fondue de taillefer"),
    ("Le Bivouaque à l'appareil", "bivouac"),
    ("La grange à Émily, bonjour", "grange a emilie"),
    ("Chez Amadoux, il me faut de la bavète", "chez amadou"),
    ("des cerneau de noix de Grenoble", "cerneaux"),
    ("du bleu du Vercor Sassenage", "bleu du vercors"),
    ("deux saucissons secs de montagne", "saucisson sec"),
    ("de la viande séchée des Alpes tranché", "viande sechee"),
    ("trois kilos de poitrine fumé", "poitrine fumee"),
    ("une tarte aux mirtilles", "myrtilles"),
]

ENGINES = [("soniox-plain", "soniox"), ("soniox-vocab", "soniox"), ("whisper-v3", "nvidia"), ("parakeet", "nvidia")]


def get(path: str, **params):
    r = httpx.get(f"{ERP}{path}", params=params, timeout=10)
    r.raise_for_status()
    return r.json()


def singular(s: str) -> str:
    return " ".join(w[:-1] if len(w) > 3 and w.endswith("s") else w for w in norm(s).split())


def covers(candidate, entity: str) -> bool:
    """The candidate's form or label contains the expected entity words (plural marks ignored)."""
    e = singular(entity)
    return any(f" {e}" in f" {singular(form)} " for form in (candidate.entry.form, candidate.entry.label))


def client_of(text: str, clients: list[dict]) -> dict | None:
    t = f" {norm(text)} "
    hits = [c for c in clients if f" {norm(c['name'])} " in t]
    return max(hits, key=lambda c: len(c["name"]), default=None)


def main() -> None:
    products, clients = get("/api/products", limit=500), get("/api/clients", limit=500)
    cat = build_catalogue(products, clients)
    print(f"lexicon: {len(cat.index)} forms ({len(products)} products, {len(clients)} clients)\n")
    refs = [client_of(text, clients) for text, _ in CORPUS]
    sheets = {c["id"]: get(f"/api/clients/{c['id']}") for c in {r["id"]: r for r in refs if r}.values()}
    lexicons = {cid: build_client(s, cat, []) for cid, s in sheets.items()}
    # truth = every entity that the REFERENCE sentence names exactly (what a perfect transcript would resolve to)
    truths = []
    for (text, _), ref in zip(CORPUS, refs):
        ixs = [cat.index] + ([lexicons[ref["id"]].index] if ref else [])
        truths.append({c.entry.entity for m in resolve(text, ixs, scope=ref["id"] if ref else None) if m.status == "exact" for c in m.candidates})

    def run(text: str, i: int, mode: str, learned: list[Learned] | None = None):
        ref = refs[i] if i is not None and i < len(refs) else None
        if mode == "A" or not ref:
            return resolve(text, [cat.index])
        cl = lexicons[ref["id"]] if not learned else build_client(sheets[ref["id"]], cat, learned)
        return resolve(text, [cat.index, cl.index], usual=cl.usual, scope=ref["id"])

    all_ms: list[float] = []
    results = {}
    for name, src in ENGINES:
        rows = json.loads((LAB / "results" / f"{src}.json").read_text())[name]
        total = sum(len(r["hits"]) for r in rows)
        raw = sum(sum(r["hits"].values()) for r in rows)
        line = {"raw": raw}
        for mode in ("A", "B", "C"):
            sure = maybe = 0
            spurious_resolved = spurious_ambiguous = 0
            wrong_sentences = redundant = 0
            for r in rows:
                learned: list[Learned] = []
                ms = run(r["hyp"], r["i"], "B")  # pass 1 (also used to know what a caller would have confirmed)
                if mode == "C" and refs[r["i"]]:
                    for m in ms:  # the caller confirmed the proposal (resolved) or picked among the candidates (ambiguous) in an earlier call
                        right = next((c for c in m.candidates if m.status != "exact" and any(not ok and covers(c, norm(e)) for e, ok in r["hits"].items())), None)
                        if right:
                            c = right.entry
                            learned.append(Learned(m.surface, c.etype, c.eid, c.label, refs[r["i"]]["id"], source="confirmed"))
                t = time.perf_counter()
                ms = run(r["hyp"], r["i"], mode if mode != "C" else "B", learned or None)
                all_ms.append((time.perf_counter() - t) * 1000)
                bad_here = False
                for e, ok in r["hits"].items():
                    if ok:
                        sure += 1
                        maybe += 1
                        continue
                    if any(m.status in ("exact", "resolved") and covers(m.best, norm(e)) for m in ms):
                        sure += 1
                        maybe += 1
                    elif any(m.status == "ambiguous" and any(covers(c, norm(e)) for c in m.candidates) for m in ms):
                        maybe += 1
                    elif mode in ("B", "C") and os.environ.get("VERBOSE"):
                        print(f"  [{name}/{mode}] still missed: {e!r} in: {r['hyp'][:90]}")
                truth = truths[r["i"]]
                for m in ms:
                    if m.status == "exact":
                        continue
                    if any(not ok and any(covers(c, norm(e)) for c in m.candidates) for e, ok in r["hits"].items()):
                        continue  # a correction of a missed entity
                    pool = [m.best] if m.status == "resolved" else m.candidates
                    if any(c.entry.entity in truth for c in pool):
                        redundant += 1  # right entity proposed for words that were already right (plural, article…): harmless
                        continue
                    bad_here = True
                    if m.status == "resolved":
                        spurious_resolved += 1
                        print(f"  [{name}/{mode}] WRONG resolved « {m.surface} » → {m.best.entry.label} ({m.best.score:.2f}) in: {r['hyp'][:80]}")
                    else:
                        spurious_ambiguous += 1
                        print(f"  [{name}/{mode}] wrong ambiguous « {m.surface} » → {' | '.join(c.entry.label for c in m.candidates[:3])} in: {r['hyp'][:80]}")
                wrong_sentences += bad_here
            line[mode] = (sure, maybe, spurious_resolved, spurious_ambiguous, wrong_sentences, redundant)
        results[name] = (total, line)

    print(f"\n{'engine':14}{'raw':>9}{'A sure':>9}{'A +amb':>9}{'B sure':>9}{'B +amb':>9}{'C sure':>9}{'C +amb':>9}   wrong resolved/ambiguous (A  B  C)   harmless-redundant (A)")
    for name, (total, ln) in results.items():
        cells = "".join(f"{ln[m][i]:>6}/{total:<2}" for m in "ABC" for i in (0, 1))
        sp = "  ".join(f"{ln[m][2]}/{ln[m][3]}" for m in "ABC")
        print(f"{name:14}{ln['raw']:>6}/{total:<2}{cells}   {sp}   {ln['A'][5]}")
    n_sent = len(CORPUS)
    print(
        f"\nwrong = a proposal that neither corrects a missed entity nor names an entity of the reference sentence, over {n_sent} sentences per engine "
        f"({n_sent * len(ENGINES)} transcripts)."
    )

    # negatives: nothing should be proposed
    neg_res = neg_amb = 0
    for s in NEGATIVES:
        for mode in ("A",):
            for m in resolve(s, [cat.index]):
                if m.status == "resolved":
                    neg_res += 1
                    print(f"  [negative] RESOLVED « {m.surface} » → {m.best.entry.label} ({m.best.score:.2f}) in: {s[:60]}")
                elif m.status == "ambiguous":
                    neg_amb += 1
                    print(f"  [negative] ambiguous « {m.surface} » → {m.best.entry.label} ({m.best.score:.2f}) in: {s[:60]}")
    cl = next(iter(lexicons.values()))
    for s in NEGATIVES:
        for m in resolve(s, [cat.index, cl.index], usual=cl.usual, scope=cl.client_id):
            if m.status == "resolved" and not any(m2.surface == m.surface for m2 in resolve(s, [cat.index]) if m2.status == "resolved"):
                print(f"  [negative+client {cl.name}] RESOLVED « {m.surface} » → {m.best.entry.label} ({m.best.score:.2f})")
    print(f"negative sentences ({len(NEGATIVES)}): resolved={neg_res} ambiguous={neg_amb} (global lexicon)")
    raw_ok = sure = maybe = 0
    for hyp, e in HELD_OUT:
        ms = resolve(hyp, [cat.index])
        raw_ok += f" {singular(e)}" in f" {singular(hyp)}"
        hit = any(m.status in ("exact", "resolved") and covers(m.best, e) for m in ms)
        sure += hit
        maybe += hit or any(m.status == "ambiguous" and any(covers(c, e) for c in m.candidates) for m in ms)
        if not hit:
            print(f"  [held-out] not resolved: {hyp!r} → {[(m.surface, m.status, m.best.entry.label) for m in ms]}")
    print(f"held-out invented slips ({len(HELD_OUT)}, not tuned on): raw {raw_ok} → resolved {sure} → with ambiguous candidates {maybe}")
    print(f"latency per sentence: median {statistics.median(all_ms):.2f} ms, p95 {sorted(all_ms)[int(len(all_ms) * 0.95)]:.2f} ms, max {max(all_ms):.2f} ms ({len(all_ms)} calls)")


if __name__ == "__main__":
    main()
