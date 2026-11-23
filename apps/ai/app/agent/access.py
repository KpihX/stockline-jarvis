"""
Enforcement of app/policy.py at the one place every tool call goes through (loop.execute_tool).

    enforce(tool, arguments, ctx)   raises AccessDenied BEFORE the tool runs (table + the checks that need the ERP or the conversation)
    guard_result(ctx, name, result) strips what the role may not read from an allowed tool's result

The model's words never decide anything here: not "je suis l'administrateur", not a clientId it invents.
"""

import re

from pydantic import ValidationError

from app.policy import DENIED_OTHER_CLIENT, AccessDenied, authorize, order_owner_ok, redact
from app.tools import Tool, ToolContext
from app.tools.erp import enc

ORDER_TOOLS = ("add_order_line", "confirm_order", "get_order")
BUILDS_ORDER = ("create_draft_order", "add_order_line")  # a recap must follow these before anything is confirmed

YES = re.compile(
    r"\b(oui|ouais|ouep|yep|yes|ok|okay|d'accord|daccord|dac|vas-y|allez|envoie|envoyez|confirme|confirmez|confirmer|valide|validez|valider|"
    r"c'est bon|c'est parfait|parfait|exact|tout à fait|bien sûr|carrément|ça marche|nickel|impeccable|go)\b",
    re.I,
)
NO = re.compile(r"\b(non|pas|annule|annulez|attends|attendez|stop|plutôt|finalement|sauf)\b", re.I)


def last_user_text(messages: list) -> str:
    """What the caller said in the current turn, without the lexicon hints the voice session appends after a blank line."""
    for m in reversed(messages):
        if m.role == "user":
            return m.content.split("\n\n[", 1)[0]
    return ""


def explicit_yes(text: str) -> bool:
    return bool(YES.search(text)) and not NO.search(text)


def confirmation_turn_ok(messages: list) -> bool:
    """The recap was given and the caller answered yes: this turn is a "yes", and the draft was not built or changed in this same turn."""
    last = max((i for i, m in enumerate(messages) if m.role == "user"), default=-1)
    for m in messages[last + 1 :]:
        if m.role == "assistant" and any(c.name in BUILDS_ORDER for c in m.tool_calls or []):
            return False
    return explicit_yes(last_user_text(messages))


async def enforce(tool: Tool, arguments: dict, ctx: ToolContext) -> None:
    caller = ctx.caller
    try:
        parsed = tool.args_model.model_validate(arguments)
    except ValidationError:
        return  # the tool will reject the same arguments itself: nothing runs
    args = {name: getattr(parsed, name) for name in type(parsed).model_fields}
    authorize(caller, tool.name, args)
    if caller.role != "client":
        return
    if tool.name in ORDER_TOOLS:
        order = await ctx.erp.get(f"/api/orders/{enc(args['order_id'])}")
        if not order_owner_ok(caller, order.get("clientId")):
            raise AccessDenied(DENIED_OTHER_CLIENT)
        if tool.name == "add_order_line" and order.get("status") != "draft":
            raise AccessDenied("Cette commande n'est plus modifiable depuis cet appel : le commercial s'en occupe.")
    if tool.name == "confirm_order" and not confirmation_turn_ok(ctx.messages or []):
        raise AccessDenied("Pas de confirmation sans récapitulatif suivi d'un « oui » explicite du client : relis la commande et attends sa réponse.")


def guard_result(ctx: ToolContext, tool_name: str, result):
    return redact(ctx.caller, tool_name, result)
