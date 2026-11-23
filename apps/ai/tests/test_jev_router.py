"""Essential unit tests for Jev routing, disambiguation, confirm_order gate, claim tagging, and cache invalidation."""

import pytest
from pydantic import create_model

from app.policy import Caller
from app.schemas import ChatMessage
from app.services import jev_router as jr
from app.tools.registry import Tool, ToolArgs, ToolContext


def make_fake_tool(name: str, fn, **fields) -> Tool:
    model = create_model(
        f"{name}_args",
        __base__=ToolArgs,
        **{k: (t if isinstance(t, tuple) else (t, ...)) for k, t in fields.items()},
    )
    return Tool(name=name, description=name, args_model=model, fn=fn)


class FakeJev:
    def __init__(self, answers: dict):
        self.answers = answers
        self.calls = 0

    async def ask(self, state, questions):
        self.calls += 1
        return {"answers": self.answers}


async def test_route_turn_fallback_without_key():
    r_triv = await jr.route_turn("merci beaucoup", jr.TurnState("merci beaucoup"))
    assert r_triv.intent == "trivial" and r_triv.tools_needed == "none"
    r_stock = await jr.route_turn("il vous reste du beaufort", jr.TurnState("il vous reste du beaufort"))
    assert r_stock.tools_needed == "read_only" and r_stock.decided_by == "fallback"


async def test_disambiguate_threshold(monkeypatch):
    mention = jr.ResolvedMention(
        heard="refuge paillet",
        candidates=[{"id": "cli_0082", "label": "Le Refuge Payet", "type": "client"}, {"id": "cli_0010", "label": "Le Crêt", "type": "client"}],
    )
    monkeypatch.setattr(jr, "get_jev_client", lambda: FakeJev({"q": {"choice": "cli_0082", "confidence": 0.91}}))
    res = await jr.disambiguate_entities([mention])
    assert res[0].status == "resolved" and res[0].candidates[0]["id"] == "cli_0082"

    monkeypatch.setattr(jr, "get_jev_client", lambda: FakeJev({"q": {"choice": "cli_0082", "confidence": 0.45}}))
    low = await jr.disambiguate_entities([mention])
    assert low[0].status == "needs_clarification"


async def test_confirm_order_gate_and_fallback(monkeypatch):
    async def _confirm(ctx: ToolContext, order_id: str) -> dict:
        return {"confirmed": order_id}

    t = make_fake_tool("confirm_order", _confirm, order_id=str)
    msgs = [ChatMessage(role="assistant", content="Je confirme 5 kg de bar ?"), ChatMessage(role="user", content="oui vas-y")]
    ctx = ToolContext(erp=None, actor="voice_agent", messages=msgs, caller=Caller.declare("client", "cli_0082"))

    monkeypatch.setattr(jr, "get_jev_client", lambda: FakeJev({"q": {"noul": 0.35}}))
    with pytest.raises(PermissionError):
        await jr.execute_with_guards(t, {"order_id": "ord_1"}, ctx)

    monkeypatch.setattr(jr, "get_jev_client", lambda: FakeJev({"q": {"noul": 0.92}}))
    out = await jr.execute_with_guards(t, {"order_id": "ord_1"}, ctx)
    assert out == {"confirmed": "ord_1"}


async def test_claim_scoring_only_tags_claims_never_blocks_normal_facts(monkeypatch):
    captured = []

    async def _save(ctx: ToolContext, entity_type: str, kind: str, title: str, body: str, entity_id: str | None = None, tags: list[str] | None = None) -> dict:
        captured.append(tags)
        return {"ok": True}

    t = make_fake_tool("save_context", _save, entity_type=str, kind=str, title=str, body=str, entity_id=(str | None, None), tags=(list[str] | None, None))
    ctx = ToolContext(erp=None, actor="voice_agent", caller=Caller.declare("client", "cli_0082"))

    monkeypatch.setattr(jr, "get_jev_client", lambda: FakeJev({"q": {"noul": 0.10}}))
    await jr.execute_with_guards(t, {"entity_type": "client", "kind": "preference", "title": "Livraison", "body": "porte de service", "entity_id": "cli_0082"}, ctx)
    assert captured[-1] is None  # normal fact not blocked and not tagged

    monkeypatch.setattr(jr, "get_jev_client", lambda: FakeJev({"q": {"noul": 0.88}}))
    await jr.execute_with_guards(t, {"entity_type": "client", "kind": "preference", "title": "Remise", "body": "30% accordé", "entity_id": "cli_0082"}, ctx)
    assert captured[-1] and "unverified" in captured[-1]


async def test_cache_scoped_and_invalidated_on_write(monkeypatch):
    calls = 0

    async def _stock(ctx: ToolContext, product_id: str) -> dict:
        nonlocal calls
        calls += 1
        return {"available": 10}

    async def _draft(ctx: ToolContext, client_id: str) -> dict:
        return {"id": "ord_1"}

    t_stock = make_fake_tool("get_product_stock", _stock, product_id=str)
    t_draft = make_fake_tool("create_draft_order", _draft, client_id=str)
    monkeypatch.setattr(jr, "get_jev_client", lambda: FakeJev({}))
    c1 = ToolContext(erp=None, actor="voice_agent", caller=Caller.declare("client", "cli_0082"))
    c2 = ToolContext(erp=None, actor="voice_agent", caller=Caller.declare("client", "cli_0033"))

    await jr.execute_with_guards(t_stock, {"product_id": "prd_1"}, c1)
    await jr.execute_with_guards(t_stock, {"product_id": "prd_1"}, c1)
    assert calls == 1
    await jr.execute_with_guards(t_stock, {"product_id": "prd_1"}, c2)
    assert calls == 2
    await jr.execute_with_guards(t_draft, {"client_id": "cli_0082"}, c1)
    await jr.execute_with_guards(t_stock, {"product_id": "prd_1"}, c1)
    assert calls == 3
