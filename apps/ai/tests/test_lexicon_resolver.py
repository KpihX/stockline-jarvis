"""Lexicon: French phonetics + the deterministic resolver (pure logic, no ERP, no network)."""

import time

import pytest

from app.lexicon import config as cfg
from app.lexicon.catalogue import build_catalogue, build_client
from app.lexicon.decide import settle
from app.lexicon.learned import Learned
from app.lexicon.phonetic import fold, key, similarity, squash, words
from app.lexicon.resolver import Candidate, Entry, Index, Mention, format_hints, resolve, tokenize

PRODUCTS = [
    {"id": "prd_0090", "name": "Apremont (vin blanc de Savoie, bouteille 75 cl)", "aliases": ["apremont", "vin blanc de Savoie"]},
    {"id": "prd_0049", "name": "Magret de canard", "aliases": ["magret", "magrets", "canard"]},
    {"id": "prd_0033", "name": "Tomme de Savoie IGP", "aliases": ["tomme", "tomme de Savoie", "tome"]},
    {"id": "prd_0056", "name": "Diots de Savoie nature", "aliases": ["diots", "diot", "saucisses de Savoie"]},
    {"id": "prd_0026", "name": "Reblochon de Savoie AOP laitier (pièce 450 g)", "aliases": ["reblochon", "reblo"]},
    {"id": "prd_0025", "name": "Reblochon de Savoie AOP fermier (pièce 450 g)", "aliases": ["reblochon fermier", "reblochon"]},
    {"id": "prd_0001", "name": "Pomme de terre Agata (sac 25 kg)", "aliases": ["patates", "patates à tartiflette"]},
]
CLIENTS = [
    {"id": "cli_0014", "name": "L'Igloo"},
    {"id": "cli_0006", "name": "Brasserie des Allobroges"},
    {"id": "cli_0033", "name": "Le Refuge Payet"},
    {"id": "cli_0034", "name": "Rémy Traiteur"},
]
SHEET = {
    "id": "cli_0033", "name": "Le Refuge Payet", "city": "Chamrousse", "zone": "Chamrousse & Belledonne",
    "contacts": [{"name": "Josiane Payet", "role": "Gérante"}, {"name": "Maël Bonnaz"}],
    "usual": [{"productId": "prd_0001", "productName": "Pomme de terre Agata (sac 25 kg)", "unit": "kg", "avgQty": 10.0, "frequency": 0.8}],
}


@pytest.fixture(scope="module")
def cat():
    return build_catalogue(PRODUCTS, CLIENTS)


def top(mentions, surface):
    return next(m for m in mentions if m.surface == surface)


# ── phonetics ──


def test_fold_and_words():
    assert fold("Hôtel Le Sérac Bleu, Œufs") == "hotel le serac bleu, oeufs"
    assert words("L'Igloo, Saint-Marcellin") == ["l", "igloo", "saint", "marcellin"]


def test_sound_alikes_share_a_key():
    assert key("Paillet") == key("Payet")  # silent letters, "ill" = y, "-et" = é
    assert key("ma graie") == key("magret")
    assert key("Liglou") != key("L'Igloo") and similarity("Liglou", "L'Igloo") > 0.85
    assert key("Rémi") == key("Remy")


def test_similarity_is_one_only_for_the_same_spelling():
    assert similarity("Le Refuge Payet", "le refuge payet") == 1.0
    assert similarity("reblochons fermiers", "reblochon fermier") == 1.0  # plural marks are not a difference
    assert similarity("Paillet", "Payet") < 0.95  # same sound, other spelling
    assert similarity("poulet", "pintade") < 0.5


def test_squash_drops_plural_marks_only_on_long_words():
    assert squash(["des", "frites"]) == "desfrite"
    assert squash(["bus", "pois"]) == "busp" + "oi"  # "bus" (3 letters) keeps its s; "pois" loses it


# ── resolver ──


def test_near_miss_client_is_resolved(cat):
    ms = resolve("Ici le refuge Paillet, rajoute des patates", [cat.index])
    m = top(ms, "refuge Paillet")
    assert m.status == "resolved" and m.best.entry.eid == "cli_0033" and 0.8 <= m.best.score < 1.0 and m.margin >= cfg.MIN_MARGIN


def test_the_catalogue_near_misses_of_the_stt_lab(cat):
    cases = [
        ("du vin blanc à Promont pour la cuisine", "à Promont", "prd_0090"),
        ("Bonjour Liglou il me faut", "Liglou", "cli_0014"),
        ("finalement pas de ma graie mais du chapon", "ma graie", "prd_0049"),
        ("vous avez de la Tombe de Savoie ?", "Tombe de Savoie", "prd_0033"),
        ("c'est la brasserie des Hallebroges", "brasserie des Hallebroges", "cli_0006"),
    ]
    for text, surface, eid in cases:
        m = top(resolve(text, [cat.index]), surface)
        assert m.status in ("resolved", "ambiguous") and eid in [c.entry.eid for c in m.candidates], (text, m)
    assert top(resolve("c'est la brasserie des Hallebroges", [cat.index]), "brasserie des Hallebroges").status == "resolved"


def test_exact_spelling_is_never_a_correction(cat):
    ms = resolve("Ici Le Refuge Payet, du magret et de la tomme", [cat.index])
    assert {m.status for m in ms} == {"exact"}
    assert [m.best.entry.eid for m in ms][:1] == ["cli_0033"]


def test_plural_and_case_are_exact(cat):
    ms = resolve("deux reblochons fermiers", [cat.index])
    assert ms and ms[0].status == "exact" and ms[0].best.entry.eid == "prd_0025"


def test_two_products_with_the_same_alias_are_ambiguous_not_guessed(cat):
    (m,) = resolve("du reblochon", [cat.index])
    assert m.status == "ambiguous" and {c.entry.eid for c in m.candidates} == {"prd_0025", "prd_0026"} and all(c.exact for c in m.candidates)


def test_ordinary_french_proposes_nothing(cat):
    for text in [
        "Pouvez-vous me rappeler vers dix heures, j'ai un souci avec mon téléphone ?",
        "Mon cousin Rémi vient m'aider samedi en salle",
        "On a eu un client très content de la salle",
        "J'ai collé un magnet sur le frigo",
        "le comptable passe vendredi pour les plats du jour",
    ]:
        assert [m for m in resolve(text, [cat.index]) if m.status != "exact"] == [], text


def test_a_mention_does_not_cross_a_comma_or_end_on_a_function_word(cat):
    ms = resolve("des patates, de la tomme", [cat.index])
    assert all(m.surface != "patates, de" for m in ms)
    assert resolve("la tombe de", [cat.index]) == [] or all(not m.surface.endswith(" de") for m in resolve("la tombe de", [cat.index]))


def test_numbers_and_common_words_are_left_alone(cat):
    assert [m for m in resolve("10 kilos de carton et 4 plateaux", [cat.index]) if m.status != "exact"] == []


def test_client_lexicon_adds_contacts_places_and_a_usual_product_prior(cat):
    lex = build_client(SHEET, cat, [])
    assert lex.terms[:2] == ["Le Refuge Payet", "Pomme de terre Agata (sac 25 kg)"] and "Josiane" in lex.terms and "Chamrousse" in lex.terms
    assert lex.usual["prd_0001"].avg_qty == 10.0
    plain = resolve("Josiane Payet au téléphone", [cat.index])
    scoped = resolve("Josiane Payet au téléphone", [cat.index, lex.index], scope="cli_0033")
    assert not any(m.best.entry.etype == "contact" for m in plain)
    assert any(m.best.entry.etype == "contact" and m.status == "exact" for m in scoped)
    # another client's private entries are never used for this caller
    assert not any(m.best.entry.etype == "contact" for m in resolve("Josiane Payet", [cat.index, lex.index], scope="cli_0006"))


def test_usual_product_prior_breaks_a_tie(cat):
    from app.lexicon.resolver import Usual

    twins = Index([Entry("brioche dorée", "product", "prd_a", "A"), Entry("brioche dorée", "product", "prd_b", "B")])
    (m,) = resolve("brioche doré", [twins])
    assert m.margin == 0.0  # two entities sound the same: nothing to choose on
    (m,) = resolve("brioche doré", [twins], usual={"prd_b": Usual("prd_b", "B")})
    assert m.best.entry.eid == "prd_b" and m.margin > 0  # the one the client usually orders leads


def test_learned_form_is_exact_for_its_client_only(cat):
    learned = [Learned("Paillet", "client", "cli_0033", "Le Refuge Payet", "global", source="spelled")]
    lex = build_client(SHEET, cat, learned)
    only_global = Index([Entry("Paillet", "client", "cli_0033", "Le Refuge Payet", "learned", "global", 0.95, "ctx_1")])
    (m,) = resolve("ici Paillet", [cat.index, only_global])
    assert m.status == "exact" and m.best.entry.source == "learned"
    mine = Index([Entry("la grosse", "product", "prd_0001", "Pomme de terre Agata", "learned", "cli_0033", 0.9, "ctx_2")])
    assert resolve("la grosse", [cat.index, mine], scope="cli_0033")[0].status == "exact"
    assert resolve("la grosse", [cat.index, mine], scope="cli_0006") == []
    assert lex.index is not None


def test_hint_block_for_the_llm(cat):
    ms = resolve("Ici le refuge Paillet, du magret", [cat.index])
    text = format_hints(ms)
    assert text.startswith("[Lexique") and "Le Refuge Payet (client cli_0033)" in text and "confirmer" in text
    assert "magret" not in text  # a word heard right is not worth a line
    ms = resolve("Ici Le Refuge Payet", [cat.index])
    assert "= Le Refuge Payet (client cli_0033)" in format_hints(ms)  # an exact client: its id saves a search
    assert format_hints(resolve("bonjour, rien de spécial", [cat.index])) == ""


def test_tokenize_keeps_the_text_as_said():
    toks = tokenize("Bonjour, le Refuge Paillet !")
    assert [t.raw for t in toks] == ["Bonjour", "le", "Refuge", "Paillet"] and toks[0].seg != toks[1].seg


# ── Jev settles ambiguities, optionally ──


class FakeJev:
    def __init__(self, choice=None, confidence=0.9, fail=False):
        self.choice, self.confidence, self.fail, self.calls = choice, confidence, fail, []

    async def choose(self, state, question, options):
        self.calls.append((state, options))
        if self.fail:
            raise RuntimeError("jev down")
        from app.clients.jev import Choice

        return Choice(self.choice or next(iter(options)), self.confidence, {k: 0.1 for k in options} | {self.choice or next(iter(options)): self.confidence})


def ambiguous(cat):
    ms = resolve("de la Tombe de Savoie", [cat.index])
    m = top(ms, "Tombe de Savoie")
    return [Mention(m.surface, m.start, m.end, "ambiguous", m.candidates, m.margin)]


async def test_jev_picks_when_confident(cat):
    (m0,) = ambiguous(cat)
    jev = FakeJev(choice=f"{m0.best.entry.etype}:{m0.best.entry.eid}", confidence=0.95)
    (m,) = await settle(jev, "de la Tombe de Savoie", [m0])
    assert m.status == "resolved" and m.decided_by == "jev" and m.best.entry.eid == m0.best.entry.eid
    assert "aucun" in jev.calls[0][1]  # a look-alike word can be rejected


async def test_jev_unsure_leaves_the_ambiguity_for_the_agent_to_ask(cat):
    (m0,) = ambiguous(cat)
    (m,) = await settle(FakeJev(confidence=0.5), "x", [m0])
    assert m.status == "ambiguous" and m.decided_by is None


async def test_jev_saying_none_drops_the_mention_and_errors_are_ignored(cat):
    (m0,) = ambiguous(cat)
    assert await settle(FakeJev(choice="aucun", confidence=0.9), "x", [m0]) == []
    (m,) = await settle(FakeJev(fail=True), "x", [m0])
    assert m.status == "ambiguous"
    (m,) = await settle(None, "x", [m0])  # no JEV_API_KEY: untouched
    assert m is m0


# ── latency (a loose bound, the measured numbers are in DECISIONS.md) ──


def test_resolver_latency_budget(cat):
    text = "Allô, Chalet Hôtel Kévin à l'appareil, je voudrais des duos de Savoie et des crozet au sarrasin, du vin blanc à Promont et la Tombe de Savoie"
    resolve(text, [cat.index])
    t = time.perf_counter()
    for _ in range(20):
        resolve(text, [cat.index])
    assert (time.perf_counter() - t) / 20 < 0.05  # 50 ms, 10x the real figure: only catches an accidental quadratic blow-up
    assert Candidate(Entry("a", "client", "cli_1", "A"), 1.0).exact is False
