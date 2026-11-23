"""Lexicon: learning only from confirmed events, persistence in the ERP context table (fake ERP), promotion, decay, unlearning."""

import json
import re

import httpx
import pytest

from app.lexicon import guard
from app.lexicon import learned as L
from app.lexicon.store import LexiconStore
from app.schemas import ChatMessage
from app.tools import TOOLS, ToolContext
from app.tools.erp import ErpClient

PRODUCTS = [
    {"id": "prd_0033", "name": "Tomme de Savoie IGP", "aliases": ["tomme", "tome"]},
    {"id": "prd_0049", "name": "Magret de canard", "aliases": ["magret", "canard"]},
]
CLIENTS = [{"id": f"cli_000{i}", "name": n} for i, n in enumerate(["", "Le Refuge Payet", "L'Igloo", "Brasserie des Allobroges", "Chez Amadou"])]
SHEETS = {c["id"]: {**c, "contacts": [], "usual": []} for c in CLIENTS}
ORDERS = {
    "ord_1": {"id": "ord_1", "status": "confirmed", "clientId": "cli_0001", "lines": [{"productId": "prd_0049"}]},
    "ord_2": {"id": "ord_2", "status": "draft", "clientId": "cli_0001", "lines": [{"productId": "prd_0049"}]},
}


class FakeErp:
    """The few ERP routes the lexicon uses, with a real, mutable context table."""

    def __init__(self):
        self.rows: dict[str, dict] = {}
        self.writes: list[tuple[str, str, dict | None, str | None]] = []  # method, path, body, x-actor

    def handler(self, req: httpx.Request) -> httpx.Response:
        path, params = req.url.path, dict(req.url.params)
        body = json.loads(req.content) if req.content else None
        if req.method != "GET":
            self.writes.append((req.method, path, body, req.headers.get("x-actor")))
        if path == "/api/products":
            return httpx.Response(200, json=PRODUCTS)
        if path == "/api/clients":
            return httpx.Response(200, json=CLIENTS)
        if m := re.fullmatch(r"/api/clients/(\w+)", path):
            return httpx.Response(200, json=SHEETS[m[1]])
        if path == "/api/meta":
            return httpx.Response(200, json={"today": getattr(self, "today", "2026-11-24")})
        if m := re.fullmatch(r"/api/orders/(\w+)", path):
            return httpx.Response(200, json=ORDERS[m[1]])
        if path == "/api/context" and req.method == "GET":
            rows = [r for r in self.rows.values() if params.get("tag") in (None, *r.get("tags", []))]
            return httpx.Response(200, json=rows[int(params.get("offset", 0)) : int(params.get("offset", 0)) + int(params.get("limit", 100))])
        if path == "/api/context" and req.method == "POST":
            row = {"id": f"ctx_{len(self.rows) + 1:04d}", "source": "voice_agent", **body}
            self.rows[row["id"]] = row
            return httpx.Response(201, json=row)
        if m := re.fullmatch(r"/api/context/(\w+)", path):
            if req.method == "PATCH":
                self.rows[m[1]].update(body)
                return httpx.Response(200, json=self.rows[m[1]])
            if req.method == "DELETE":
                del self.rows[m[1]]
                return httpx.Response(200, json={"ok": True})
        return httpx.Response(404, json={"error": {"message": f"no route {req.method} {path}"}})

    def erp(self, actor="voice_agent") -> ErpClient:
        return ErpClient(actor, base_url="http://erp.test", http=httpx.AsyncClient(transport=httpx.MockTransport(self.handler)))


@pytest.fixture
def fake():
    return FakeErp()


@pytest.fixture
def store(fake):
    return LexiconStore(fake.erp)


def msgs(*turns):
    return [t if isinstance(t, ChatMessage) else ChatMessage(role=t[0], content=t[1]) for t in turns]


# ── the pure rules ──


def test_row_round_trip_is_lossless_and_human_readable():
    e = L.Learned("Paillet", "client", "cli_0001", "Le Refuge Payet", "global", 2, "2026-11-20", "2026-11-24", "spelled", ["cli_0001"])
    row = L.encode(e)
    assert row["entityType"] == "client" and row["entityId"] == "cli_0001" and row["kind"] == "fact" and row["tags"] == ["vocab", "vocab:client"]
    assert row["title"] == "Vocabulaire : « Paillet » → Le Refuge Payet" and "Appris par l'agent vocal" in row["body"].splitlines()[0]
    back = L.decode({**row, "id": "ctx_9"})
    assert back.row_id == "ctx_9" and (back.heard, back.eid, back.scope, back.count, back.source) == ("Paillet", "cli_0001", "global", 2, "spelled")
    assert L.decode({"tags": ["autre"], "body": row["body"]}) is None  # not a vocabulary row
    assert L.decode({"tags": ["vocab"], "body": "pas de json"}) is None


def test_anchor_rows():
    assert L.Learned("x", "product", "prd_1", "P", "cli_0002").anchor == ("client", "cli_0002")
    assert L.Learned("x", "product", "prd_1", "P", "global").anchor == ("company", None)
    assert L.Learned("x", "client", "cli_0002", "C", "global").anchor == ("client", "cli_0002")


def test_validate_refuses_junk_and_nothing_to_learn():
    assert L.validate("  la  grosse ", "product", "prd_1", "Pomme de terre") == "la grosse"
    for bad in [("", "product", "prd_1", "X"), ("12", "product", "prd_1", "X"), ("a b c d e f g", "product", "prd_1", "X"),
                ("Magrets", "product", "prd_1", "Magret"), ("x", "supplier", "s", "S"), ("x", "product", None, "X")]:  # fmt: skip
        with pytest.raises(L.LearnRefused):
            L.validate(*bad)


def test_merge_counts_and_keeps_the_strongest_proof():
    first = L.merge(None, L.Learned("tombe", "product", "prd_0033", "Tomme", "cli_0001", source="confirmed", clients=["cli_0001"]), "2026-11-20")
    again = L.merge(first, L.Learned("tombe", "product", "prd_0033", "Tomme", "cli_0001", source="spelled", clients=["cli_0001"]), "2026-11-24")
    assert (again.count, again.first_seen, again.last_seen, again.source) == (2, "2026-11-20", "2026-11-24", "spelled")
    assert again.confidence > first.confidence and again.confidence <= 0.99


def test_decay_unused_entries_expire_sooner_than_reused_ones():
    once = L.Learned("x", "product", "p", "P", "cli_1", 1, "2026-01-01", "2026-01-01")
    twice = L.Learned("x", "product", "p", "P", "cli_1", 2, "2026-01-01", "2026-01-01")
    assert not L.expired(once, "2026-01-20") and L.expired(once, "2026-03-01")
    assert not L.expired(twice, "2026-03-01") and L.expired(twice, "2026-11-01")
    assert not L.expired(L.Learned("x", "product", "p", "P", "cli_1", 1, "", ""), "2030-01-01")  # undated: kept


def test_promotion_needs_distinct_clients_and_is_not_repeated():
    def row(scope, count=1, etype="product"):
        return L.Learned("tombe", etype, "prd_0033", "Tomme", scope, count, "2026-11-01", "2026-11-20", "confirmed")

    assert L.promotions([row("cli_1"), row("cli_2")], "2026-11-24") == []  # 2 < PROMOTE_MIN_CLIENTS
    assert L.promotions([row("cli_1", 5)], "2026-11-24") == []  # one client confirming many times is still one client
    (p,) = L.promotions([row("cli_1"), row("cli_2"), row("cli_3")], "2026-11-24")
    assert p.scope == "global" and p.clients == ["cli_1", "cli_2", "cli_3"] and p.count == 3
    assert L.promotions([row("cli_1"), row("cli_2"), row("cli_3"), row("global")], "2026-11-24") == []
    assert L.promotions([row("cli_1", etype="client"), row("cli_2", etype="client"), row("cli_3", etype="client")], "2026-11-24") == []
    stale = [row(f"cli_{i}") for i in (1, 2)] + [L.Learned("tombe", "product", "prd_0033", "Tomme", "cli_3", 1, "2025-01-01", "2025-01-01")]
    assert L.promotions(stale, "2026-11-24") == []  # an expired lesson does not count


# ── the guard: the conversation must prove it ──

PAILLET = [("user", "Ici le refuge Paillet"), ("assistant", "Le Refuge Payet, c'est bien ça ?")]


async def test_confirmed_needs_the_name_repeated_and_a_yes():
    ok = msgs(*PAILLET, ("user", "Oui c'est ça"))
    await guard.check_evidence("confirmed", "Paillet", "Le Refuge Payet", ok)
    for convo, why in [
        (msgs(("user", "Ici le refuge Paillet")), "no answer yet"),
        (msgs(("user", "Ici le refuge Paillet"), ("assistant", "Bonjour, que puis-je faire ?"), ("user", "oui")), "the name was never repeated"),
        (msgs(*PAILLET, ("user", "Non, pas du tout")), "a no"),
        (msgs(*PAILLET, ("user", "Euh, je ne sais pas, passez-moi du magret")), "no clear yes"),
        (msgs(("user", "bonjour"), ("assistant", "Le Refuge Payet, c'est bien ça ?"), ("user", "oui")), "the word was never said"),
    ]:
        with pytest.raises(L.LearnRefused):
            await guard.check_evidence("confirmed", "Paillet", "Le Refuge Payet", convo)
        assert why


async def test_the_lexicon_block_is_not_the_callers_words():
    convo = msgs(("user", "bonjour\n\n[Lexique : aide à l'écoute]\n- « Paillet » ressemble à Le Refuge Payet"), ("assistant", "Le Refuge Payet ?"), ("user", "oui"))
    with pytest.raises(L.LearnRefused, match="pas été dit"):
        await guard.check_evidence("confirmed", "Paillet", "Le Refuge Payet", convo)


async def test_jev_has_the_last_word_when_there_is_one_and_falls_back_when_it_fails():
    convo = msgs(*PAILLET, ("user", "Oui c'est ça"))

    async def jev_no(q, a):
        return False

    async def jev_unsure(q, a):
        return None

    async def jev_down(q, a):
        raise RuntimeError("down")

    with pytest.raises(L.LearnRefused):
        await guard.check_evidence("confirmed", "Paillet", "Le Refuge Payet", convo, ask_yes=jev_no)
    await guard.check_evidence("confirmed", "Paillet", "Le Refuge Payet", convo, ask_yes=jev_unsure)  # unsure → the word list says yes
    await guard.check_evidence("confirmed", "Paillet", "Le Refuge Payet", convo, ask_yes=jev_down)  # error → the word list says yes


async def test_spelled_letters_must_match_the_name():
    good = msgs(("user", "Ici le refuge Paillet"), ("assistant", "Pouvez-vous épeler ?"), ("user", "P A Y E T"))
    await guard.check_evidence("spelled", "Paillet", "Le Refuge Payet", good)
    await guard.check_evidence("spelled", "Paillet", "Le Refuge Payet", msgs(*good[:2], ("user", "P comme Pierre, A comme Alain, Y comme Yves, E comme Eric, T comme Thierry")))
    for wrong in ["B O U C H O N", "oui c'est ça", "payet"]:  # other letters, a plain yes, a word that is not spelled
        with pytest.raises(L.LearnRefused):
            await guard.check_evidence("spelled", "Paillet", "Le Refuge Payet", msgs(*good[:2], ("user", wrong)))


def test_spelled_letters_extraction():
    assert guard.spelled_letters("P-A-Y-E-T") == "payet"
    assert guard.spelled_letters("ça s'écrit p a y e t voilà") == "payet"
    assert guard.spelled_letters("bonjour tout le monde") == ""


async def test_order_evidence_needs_a_confirmed_order_of_this_client_with_the_product():
    await guard.check_evidence("order", "ma graie", "Magret de canard", [], order=ORDERS["ord_1"], client_id="cli_0001", etype="product", eid="prd_0049")
    for order, client, eid in [(ORDERS["ord_2"], "cli_0001", "prd_0049"), (ORDERS["ord_1"], "cli_0002", "prd_0049"), (ORDERS["ord_1"], "cli_0001", "prd_0033"), (None, "cli_0001", "prd_0049")]:
        with pytest.raises(L.LearnRefused):
            await guard.check_evidence("order", "x", "Magret", [], order=order, client_id=client, etype="product", eid=eid)


# ── persistence in the ERP context table ──


async def test_learn_writes_a_context_row_with_the_actor_then_counts_up(store, fake):
    r1 = await store.learn(fake.erp("voice_agent"), "cli_0001", "tombe de savoie", "product", "prd_0033", "ignored label", "confirmed")
    assert r1 == {"id": "ctx_0001", "scope": "cli_0001", "count": 1, "confidence": 0.85, "promotedToGlobal": False}
    (method, path, body, actor) = fake.writes[0]
    assert (method, path, actor) == ("POST", "/api/context", "voice_agent")
    assert body["entityType"] == "client" and body["entityId"] == "cli_0001" and "vocab" in body["tags"] and "Tomme de Savoie" in body["title"]  # the ERP's name, not the model's
    r2 = await store.learn(fake.erp(), "cli_0001", "Tombe de Savoie", "product", "prd_0033", "x", "spelled")  # same lesson, other case
    assert (r2["id"], r2["count"]) == ("ctx_0001", 2) and len(fake.rows) == 1 and fake.writes[1][0] == "PATCH"
    assert L.decode(fake.rows["ctx_0001"]).source == "spelled"


async def test_the_lexicon_survives_a_restart_because_it_lives_in_the_erp(store, fake):
    await store.learn(fake.erp(), "cli_0001", "tombe", "product", "prd_0033", "x", "confirmed")
    reborn = LexiconStore(fake.erp)  # a new process: empty memory
    mine = [r.heard for r in await reborn.learned() if r.scope == "cli_0001"]
    assert mine == ["tombe"]
    ix = await reborn.indexes("cli_0001")
    assert any(e.source == "learned" and e.form == "tombe" for e in ix.indexes[-1].entries)
    ix_other = await reborn.indexes("cli_0002")
    assert not any(e.form == "tombe" for e in ix_other.indexes[-1].entries)  # another client does not inherit it


async def test_a_client_designation_is_global_from_the_start(store, fake):
    r = await store.learn(fake.erp(), "cli_0001", "Paillet", "client", "cli_0001", "x", "spelled")
    assert r["scope"] == "global"  # the caller says their own name BEFORE being identified
    ix = await store.indexes(None)  # nobody identified yet
    assert any(e.form == "Paillet" and e.source == "learned" for e in ix.indexes[1].entries)


async def test_three_distinct_clients_promote_a_pair_to_the_global_lexicon(store, fake):
    for cid in ("cli_0001", "cli_0002"):
        assert (await store.learn(fake.erp(), cid, "tombe", "product", "prd_0033", "x", "confirmed"))["promotedToGlobal"] is False
    await store.learn(fake.erp(), "cli_0001", "tombe", "product", "prd_0033", "x", "confirmed")  # the same client again: still 2 clients
    assert not any(r.scope == "global" for r in await store.learned())
    assert (await store.learn(fake.erp(), "cli_0003", "tombe", "product", "prd_0033", "x", "confirmed"))["promotedToGlobal"] is True
    assert sum(1 for r in await store.learned() if r.scope == "global") == 1
    ix = await store.indexes("cli_0004")  # a client who never said it benefits
    assert any(e.form == "tombe" for e in ix.indexes[1].entries)
    await store.learn(fake.erp(), "cli_0004", "tombe", "product", "prd_0033", "x", "confirmed")  # a 4th confirmation does not duplicate the global row
    assert sum(1 for r in await store.learned() if r.scope == "global") == 1


async def test_learn_refuses_what_would_poison_the_catalogue_or_is_not_real(store, fake):
    with pytest.raises(L.LearnRefused, match="déjà"):  # "magret" already means Magret de canard
        await store.learn(fake.erp(), "cli_0001", "magret", "product", "prd_0033", "x", "confirmed")
    with pytest.raises(L.LearnRefused, match="Client inconnu"):
        await store.learn(fake.erp(), "cli_9999", "tombe", "product", "prd_0033", "x", "confirmed")
    with pytest.raises(L.LearnRefused, match="Identifiant inconnu"):
        await store.learn(fake.erp(), "cli_0001", "tombe", "product", "prd_9999", "x", "confirmed")
    assert fake.rows == {}


async def test_forget_and_forget_heard_remove_the_row(store, fake):
    await store.learn(fake.erp(), "cli_0001", "tombe", "product", "prd_0033", "x", "confirmed")
    await store.learn(fake.erp(), "cli_0002", "tombe", "product", "prd_0033", "x", "confirmed")
    out = await store.forget_heard(fake.erp(), "Tombe", "cli_0001")
    assert [o["scope"] for o in out] == ["cli_0001"] and len(fake.rows) == 1
    assert (await store.forget(fake.erp("user"), "ctx_0002"))["forgot"] == "tombe" and fake.rows == {}
    assert fake.writes[-1][3] == "user"
    with pytest.raises(LookupError):
        await store.forget(fake.erp(), "ctx_0002")


async def test_prune_deletes_only_expired_entries(store, fake):
    fake.today = "2026-01-01"
    await store.learn(fake.erp(), "cli_0001", "tombe", "product", "prd_0033", "x", "confirmed")  # once
    await store.learn(fake.erp(), "cli_0002", "toumme", "product", "prd_0033", "x", "confirmed")
    await store.learn(fake.erp(), "cli_0002", "toumme", "product", "prd_0033", "x", "confirmed")  # twice
    store._today = ("", 0.0)
    fake.today = "2026-03-15"  # 73 days later: the one-shot lesson is stale, the repeated one lives on
    assert [r.heard for r in await store.learned()] == ["toumme"]  # expired entries are ignored at read time...
    assert len(await store.prune(fake.erp("user"))) == 1 and [r["title"] for r in fake.rows.values()] == ["Vocabulaire : « toumme » → Tomme de Savoie IGP"]  # ...and removable


async def test_no_erp_means_no_lexicon_not_an_error():
    from tests.conftest import down

    s = LexiconStore(down)
    assert await s.indexes("cli_0001") is None and await s.client_terms("cli_0001") == [] and await s.learned() == [] and await s.ready(0.1) is False


async def test_client_terms_come_from_the_sheet_and_the_lessons(store, fake):
    SHEETS["cli_0001"] = {**SHEETS["cli_0001"], "city": "Chamrousse", "contacts": [{"name": "Josiane Payet"}], "usual": [{"productId": "prd_0049", "productName": "Magret de canard", "unit": "kg", "avgQty": 4.0, "frequency": 0.9}]}
    await store.learn(fake.erp(), "cli_0001", "ma graie", "product", "prd_0049", "x", "confirmed")
    terms = await store.client_terms("cli_0001")
    assert terms[0] == "Le Refuge Payet" and terms[1] == "Magret de canard" and {"Josiane Payet", "Josiane", "Chamrousse"} <= set(terms)
    assert "ma graie" not in terms  # a heard form is never sent to the STT as a term (it would bias towards the mistake)


# ── the tools the agent calls ──


def ctx_for(fake, messages):
    return ToolContext(erp=fake.erp(), actor="voice_agent", messages=messages)


@pytest.fixture
def tools_store(monkeypatch, store):
    import app.lexicon.store as store_module

    for name in ("catalogue", "learn", "forget_heard", "client", "learned", "today", "indexes"):
        monkeypatch.setattr(store_module.store, name, getattr(store, name))
    return store


async def test_learn_term_refuses_without_a_confirmation_and_learns_after_one(tools_store, fake):
    learn = TOOLS["learn_term"]
    args = {"clientId": "cli_0001", "heard": "Paillet", "entityType": "client", "entityId": "cli_0001", "evidence": "confirmed"}
    for convo in [msgs(("user", "Ici le refuge Paillet")), msgs(*PAILLET), msgs(*PAILLET, ("user", "non"))]:
        with pytest.raises(L.LearnRefused):
            await learn.run(args, ctx_for(fake, convo))
    assert fake.rows == {}  # nothing written on a guess
    out = await learn.run(args, ctx_for(fake, msgs(*PAILLET, ("user", "oui exactement"))))
    assert out["learned"] is True and out["scope"] == "global" and len(fake.rows) == 1
    forget = await TOOLS["forget_term"].run({"heard": "paillet"}, ctx_for(fake, []))
    assert forget["forgot"][0]["forgot"] == "Paillet" and fake.rows == {}
    with pytest.raises(LookupError):
        await TOOLS["forget_term"].run({"heard": "paillet"}, ctx_for(fake, []))


async def test_learn_term_order_evidence_checks_the_erp_order(tools_store, fake):
    args = {"clientId": "cli_0001", "heard": "ma graie", "entityType": "product", "entityId": "prd_0049", "evidence": "order", "orderId": "ord_2"}
    with pytest.raises(L.LearnRefused, match="pas confirmée"):
        await TOOLS["learn_term"].run(args, ctx_for(fake, []))
    out = await TOOLS["learn_term"].run({**args, "orderId": "ord_1"}, ctx_for(fake, []))
    assert out["learned"] and out["confidence"] == 0.9


async def test_resolve_mention_tool_returns_small_json(tools_store, fake):
    out = await TOOLS["resolve_mention"].run({"text": "ici le refuge Paillet"}, ctx_for(fake, []))
    assert out[0]["status"] == "resolved" and out[0]["candidates"][0]["id"] == "cli_0001" and "confirmer" in out[0]["action"]
    assert (await TOOLS["resolve_mention"].run({"text": "bonjour tout le monde"}, ctx_for(fake, [])))[0]["status"] == "no_match"


def test_vocabulary_rows_are_hidden_from_the_context_tools():
    from app.tools.context import is_vocab

    assert is_vocab({"tags": ["vocab", "vocab:client"]}) and not is_vocab({"tags": ["preference"]}) and not is_vocab({})
