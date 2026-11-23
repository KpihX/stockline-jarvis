"""Compaction of a long call (services/compaction.py): business facts survive, chatter goes, no tool call is ever left dangling. Pure logic, no I/O."""

import json

from app.agent.sanitize import sanitize_history
from app.schemas import ChatMessage, ToolCall
from app.services import compaction
from app.services.compaction import (
    SUMMARY_ACK,
    SUMMARY_MARK,
    Policy,
    compact,
    extract,
    is_summary,
    needs_compaction,
    render,
    split_turns,
)


def user(text):
    return ChatMessage(role="user", content=text)


def agent(text):
    return ChatMessage(role="assistant", content=text)


def calls(*specs, text=""):
    return ChatMessage(role="assistant", content=text, tool_calls=[ToolCall(id=i, name=n, arguments=a) for i, n, a in specs])


def result(call_id, name, payload):
    return ChatMessage(role="tool", tool_call_id=call_id, name=name, content=json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


ORDER = {
    "id": "ord_0345",
    "number": "CMD-2026-000345",
    "status": "draft",
    "client": "Chalet du Recoin",
    "deliveryDate": "2026-11-26",
    "totalHt": 85.0,
    "lines": [{"lineId": "l1", "productId": "prd_0056", "productName": "Diots de Savoie", "qty": 10, "unit": "kg", "unitPrice": 8.5}],
    "warnings": ["Encours proche de la limite"],
}


def order_call():
    """One real-looking ordering call: search → client → draft order with a line, then a recap question."""
    return [
        user("Bonjour, ici le Chalet du Recoin, je voudrais dix kilos de diots pour jeudi"),
        calls(("c1", "search", {"query": "Chalet du Recoin"})),
        result("c1", "search", [{"type": "client", "id": "cli_0012", "label": "Chalet du Recoin"}, {"type": "client", "id": "cli_0099", "label": "Chalet du Pin"}]),
        calls(("c2", "get_client", {"client_id": "cli_0012"}), ("c3", "search", {"query": "diots"})),
        result("c2", "get_client", {"id": "cli_0012", "name": "Chalet du Recoin", "status": "active"}),
        result("c3", "search", [{"type": "product", "id": "prd_0056", "label": "Diots de Savoie"}]),
        calls(("c4", "create_draft_order", {"client_id": "cli_0012", "delivery_date": "2026-11-26", "lines": [{"productId": "prd_0056", "qty": 10}]})),
        result("c4", "create_draft_order", ORDER),
        agent("C'est noté : dix kilos de diots de Savoie à 8,50 euros pour jeudi 26. Je confirme la commande ?"),
    ]


def chatter(n):
    names = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel", "india", "juliet", "kilo", "lima", "mike", "nectar", "oscar", "papa"]
    out = []
    for i in range(n):
        out += [user(f"merci, et la météo {names[i % 16]} ?"), agent(f"Je ne peux pas vous renseigner sur la météo {names[i % 16]}, mais je reste là pour la commande.")]
    return out


def assert_paired(history):
    assert history == sanitize_history(history), "sanitize_history would still change it: a call is dangling or an orphan result is left"
    for i, m in enumerate(history):
        if m.tool_calls:
            followers = [x.tool_call_id for x in history[i + 1 : i + 1 + len(m.tool_calls)]]
            assert followers == [c.id for c in m.tool_calls]


# ── what must be retained ──


def test_facts_keep_client_order_ids_lines_prices_and_dates():
    facts = extract(split_turns(order_call()))
    text = render(facts)
    for must in ("cli_0012", "Chalet du Recoin", "ord_0345", "CMD-2026-000345", "prd_0056", "Diots de Savoie", "10 kg", "8.5", "2026-11-26", "85.0", "brouillon" if False else "draft"):
        assert must in text, must
    assert "Encours proche de la limite" in text  # the ERP's warning is a fact
    assert "create_draft_order" in text and "→ ok" in text  # the write action is logged
    assert "cli_0099" not in text and "Chalet du Pin" not in text  # an unchosen search candidate is chatter
    assert text.startswith(SUMMARY_MARK)


def test_unverified_claims_are_labelled_and_the_pending_question_kept():
    text = render(extract(split_turns(order_call())))
    assert "NON vérifié" in text and "dix kilos de diots pour jeudi" in text  # what the caller said, as said
    assert "Question restée en attente : Je confirme la commande ?" in text


def test_a_failed_write_is_reported_as_an_error():
    turn = [
        user("confirmez"),
        calls(("c9", "confirm_order", {"order_id": "ord_0345"})),
        result("c9", "confirm_order", {"error": "Encours dépassé : client bloqué"}),
        agent("Je n'ai pas pu confirmer : le client est bloqué."),
    ]
    text = render(extract(split_turns(turn)))
    assert "confirm_order(order_id=ord_0345) → ERREUR : Encours dépassé" in text


def test_the_latest_state_of_an_order_wins():
    later = {**ORDER, "status": "confirmed", "totalHt": 120.0}
    turns = split_turns([*order_call(), user("ok"), calls(("c5", "confirm_order", {"order_id": "ord_0345"})), result("c5", "confirm_order", later), agent("Confirmée.")])
    text = render(extract(turns))
    assert "confirmed" in text and "120.0" in text and "85.0" not in text


def test_lexicon_hint_block_is_not_kept_as_caller_words():
    hinted = user("du beaufort 18 euros\n\n[Lexique : aide à l'écoute, ce n'est pas ce que l'appelant a dit]\nprd_0031 ≈ beaufort")
    text = render(extract([[hinted, agent("ok")]]))
    assert "du beaufort 18 euros" in text and "Lexique" not in text and "prd_0031" not in text


# ── compaction itself ──


def long_call():
    return [*order_call(), *chatter(14), user("Et pour ma commande, c'est bien dix kilos ?"), agent("Oui, dix kilos de diots, jeudi 26.")]


def test_nothing_to_do_on_a_short_history():
    short = [*order_call(), *chatter(3)]
    assert not needs_compaction(short)
    out, facts, folded = compact(short)
    assert out is short and folded == 0


def test_compaction_keeps_the_last_turns_verbatim_and_folds_the_rest():
    history = long_call()
    assert needs_compaction(history)
    out, facts, folded = compact(history)
    assert is_summary(out[0]) and out[1] == ChatMessage(role="assistant", content=SUMMARY_ACK)
    tail_turns = split_turns(out[2:])
    assert len(tail_turns) == Policy().keep_turns
    assert out[2:] == history[-len(out[2:]) :]  # the kept turns are the original messages, untouched
    assert folded == len(history) - len(out[2:])
    assert len(out) < len(history)
    assert_paired(out)
    # the facts of the FOLDED part (turn 1) survived: order, client, price, pending question context
    head = out[0].content
    for must in ("cli_0012", "ord_0345", "prd_0056", "8.5", "2026-11-26"):
        assert must in head, must
    assert "météo" not in head  # chatter is gone


def test_compaction_never_cuts_a_tool_call_from_its_result():
    # a tool round inside the KEPT part and one in the folded part; cut at every possible history length
    base = [*order_call(), *chatter(8)] + order_call() + chatter(2)
    for n in range(len(base)):
        h = sanitize_history(base[:n]) if n else []
        out, _, _ = compact(h, policy=Policy(keep_turns=2, trigger_turns=3))
        assert_paired(out)
        if out and out is not h:
            assert out[0].role == "user" and is_summary(out[0])


def test_second_compaction_merges_with_the_first_instead_of_losing_it():
    policy = Policy(keep_turns=3, trigger_turns=5)
    first, facts1, _ = compact(long_call(), None, policy)
    more = [*first, *chatter(6), user("Ajoute aussi trois kilos de reblochon"), calls(("d1", "search", {"query": "reblochon"})), result("d1", "search", [{"type": "product", "id": "prd_0031", "label": "Reblochon"}]),
            calls(("d2", "add_order_line", {"order_id": "ord_0345", "product_id": "prd_0031", "qty": 3})),
            result("d2", "add_order_line", {**ORDER, "lines": [*ORDER["lines"], {"lineId": "l2", "productId": "prd_0031", "productName": "Reblochon", "qty": 3, "unit": "kg", "unitPrice": 21.0}], "totalHt": 148.0}),
            agent("Trois kilos de reblochon ajoutés."), *chatter(4)]
    second, facts2, folded = compact(more, facts1, policy)
    text = second[0].content
    assert second[0] is not first[0] and folded > 0
    assert sum(is_summary(m) for m in second) == 1  # one summary, the old one was replaced, not stacked
    for must in ("cli_0012", "ord_0345", "Diots de Savoie", "Reblochon", "prd_0031", "148.0"):
        assert must in text, must
    assert_paired(second)


def test_facts_are_ignored_without_a_summary_at_the_head():
    """After a reset / identity change the history is empty again: stale facts must not leak into the next summary."""
    stale = extract(split_turns(order_call()))
    out, facts, _ = compact([*chatter(10)], stale, Policy(keep_turns=2, trigger_turns=4))
    assert "ord_0345" not in out[0].content and facts["orders"] == {}


def test_size_trigger_compacts_a_short_but_heavy_history():
    big = {"id": "prd_0001", "name": "X", "blob": "y" * 4000}
    heavy = [m for i in range(10) for m in (user(f"q{i}"), calls((f"h{i}", "get_client", {"client_id": "cli_0001"})), result(f"h{i}", "get_client", big), agent("ok"))]
    assert len(split_turns(heavy)) == 10 <= Policy().trigger_turns
    assert needs_compaction(heavy, Policy(max_chars=20_000))


def test_summary_stays_small_whatever_the_history():
    many = []
    for i in range(60):
        many += [user(f"je voudrais {i} kilos de produit {i} pour demain"), agent(f"réponse {i} ?")]
    out, _, _ = compact(many, None, Policy(keep_turns=4, trigger_turns=8))
    assert len(out[0].content) <= compaction.SUMMARY_MAX_CHARS


# ── optional LLM refinement: can only compress, never drop an id ──


class Scripted:
    provider, model = "scripted", "m"

    def __init__(self, reply=None, boom=False):
        self.reply, self.boom = reply, boom

    async def stream(self, request):
        from app.clients import LLMText

        if self.boom:
            raise RuntimeError("provider down")
        yield LLMText(self.reply)


async def test_refine_accepts_a_shorter_summary_with_all_ids():
    text = render(extract(split_turns(order_call())))
    good = f"{SUMMARY_MARK} : cli_0012, ord_0345, prd_0056 : 10 kg diots 8.5 €, jeudi 26.]"
    assert await compaction.refine(Scripted(good), text) == good


async def test_refine_rejects_a_dropped_id_a_missing_mark_a_longer_text_and_provider_errors():
    text = render(extract(split_turns(order_call())))
    assert await compaction.refine(Scripted(f"{SUMMARY_MARK} : cli_0012 seulement]"), text) is None  # ord_ / prd_ lost
    assert await compaction.refine(Scripted("cli_0012 ord_0345 prd_0056"), text) is None  # no mark
    assert await compaction.refine(Scripted(text + " et plus"), text) is None  # not shorter
    assert await compaction.refine(Scripted(boom=True), text) is None  # provider error: the deterministic summary stays
