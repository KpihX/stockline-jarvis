"""
The learn-only-from-a-confirmed-event guard. A lesson is recorded ONLY when the conversation itself proves it:

    spelled    the caller said the word, the agent asked "pouvez-vous épeler ?", and a LATER caller message spells letters
               that match the entity's name ("P A Y E T", "P comme Pierre, A comme …")
    confirmed  the caller said the word, the agent repeated the entity's name back ("c'est bien Le Refuge Payet ?") and the
               caller's LAST message is a yes (Jev `is_yes` when a key is set, else a conservative word list)
    order      the order line was confirmed in the ERP (status not draft, same client, the product is on it)

The agent cannot lie its way through: the check reads the real conversation (`ToolContext.messages`), not the agent's claim.
Pure functions + one optional Jev call; everything raises LearnRefused with a French message the agent can act on.
"""

import re
from collections.abc import Awaitable, Callable

from .learned import LearnRefused, squash_form
from .phonetic import spelling_similarity, words

HINT_MARK = "\n\n[Lexique"  # the resolver's block, appended to a spoken user turn (voice_session): not the caller's words

YES = re.compile(r"\b(oui|ouais|ouep|exact|exactement|tout a fait|c est (?:bien )?ca|c est bien|voila|absolument|bien sur|d accord|parfait|yes)\b")
NO = re.compile(r"\b(non|nan|pas du tout|pas ca|c est pas|ce n est pas|faux|pas vraiment)\b")


def said(content: str) -> str:
    """What the caller actually said: the resolver's block is cut off."""
    return content.split(HINT_MARK, 1)[0]


def contains(text: str, phrase: str) -> bool:
    """The phrase's words appear in order and contiguous in the text (folded, plural marks ignored)."""
    t, p = [squash_form(w) for w in words(text)], [squash_form(w) for w in words(phrase)]
    return bool(p) and any(t[i : i + len(p)] == p for i in range(len(t) - len(p) + 1))


def spelled_letters(text: str) -> str:
    """The longest run of spelled letters in a message: "P A Y E T" → "payet", "P comme Pierre A comme Alain" → "pa"."""
    toks = words(text)
    runs, run, i = [], "", 0
    while i < len(toks):
        t = toks[i]
        if len(t) == 1 and t.isalpha():
            run += t
            i += 1
            if i + 1 < len(toks) and toks[i] == "comme":  # "P comme Pierre": the letter is counted, skip "comme Pierre"
                i += 2
        else:
            if run:
                runs.append(run)
            run, i = "", i + 1
    if run:
        runs.append(run)
    return max(runs, key=len, default="")


def is_yes_words(text: str) -> bool | None:
    """Conservative fallback when Jev is not available: a clear yes → True, a clear no → False, else None."""
    t = " ".join(words(text))
    if NO.search(t):
        return False
    return True if YES.search(t) else None


async def check_evidence(
    evidence: str,
    heard: str,
    label: str,
    messages: list,
    *,
    ask_yes: Callable[[str, str], Awaitable[bool | None]] | None = None,
    order: dict | None = None,
    client_id: str | None = None,
    etype: str = "product",
    eid: str | None = None,
) -> None:
    """Raise LearnRefused unless `evidence` is proven by `messages` (the conversation, ChatMessage-like: role, content).
    `ask_yes(question, answer)`: Jev's is_yes (True/False/None), optional. `order`: the ERP order for evidence="order"."""
    if evidence == "order":
        _check_order(order, client_id, etype, eid)
        return
    turns = [(i, m.role, said(m.content or "")) for i, m in enumerate(messages) if m.role in ("user", "assistant") and (m.content or "").strip()]
    users = [t for t in turns if t[1] == "user"]
    said_at = next((i for i, _, text in reversed(users) if contains(text, heard)), None)
    if said_at is None:
        raise LearnRefused(f"« {heard} » n'a pas été dit par l'appelant pendant cet appel : je n'apprends que ce qui a été réellement entendu.")
    later = [t for t in users if t[0] > said_at]
    if not later:
        raise LearnRefused("Pas encore de réponse de l'appelant : demande-lui de confirmer ou d'épeler, puis réessaie.")

    if evidence == "spelled":
        forms = [*words(label)]
        for _, _, text in later:
            letters = spelled_letters(text)
            if len(letters) >= 3 and any(spelling_similarity(letters, w) >= 0.75 for w in forms if len(w) >= 3):
                return
        raise LearnRefused("Aucune épellation de l'appelant ne correspond à ce nom : demande-lui d'épeler, ou utilise evidence=confirmed après un « oui ».")

    if evidence == "confirmed":
        last_i, _, answer = later[-1]
        asked = [(i, text) for i, role, text in turns if role == "assistant" and said_at < i < last_i]
        question = next((text for i, text in reversed(asked) if contains(text, label)), None)
        if question is None:
            raise LearnRefused(f"Tu n'as pas répété « {label} » à l'appelant : demande « c'est bien {label} ? » et attends son oui avant d'apprendre.")
        verdict = None
        if ask_yes:
            try:
                verdict = await ask_yes(question, answer)
            except Exception:  # Jev down: the word list decides
                verdict = None
        if verdict is None:
            verdict = is_yes_words(answer)
        if verdict is not True:
            raise LearnRefused("La dernière réponse de l'appelant n'est pas un oui clair : je n'apprends rien (redemande ou fais épeler).")
        return
    raise LearnRefused(f"Preuve inconnue : {evidence} (spelled, confirmed ou order).")


def _check_order(order: dict | None, client_id: str | None, etype: str, eid: str | None) -> None:
    if not order:
        raise LearnRefused("evidence=order demande orderId (commande confirmée).")
    if order.get("status") in (None, "draft", "cancelled"):
        raise LearnRefused("La commande n'est pas confirmée dans l'ERP : rien à apprendre tant que l'appelant n'a pas dit oui au récapitulatif.")
    if order.get("clientId") != client_id:
        raise LearnRefused("Cette commande n'est pas celle de ce client.")
    if etype == "product" and eid not in {line.get("productId") for line in order.get("lines") or []}:
        raise LearnRefused("Ce produit n'est pas dans la commande confirmée.")
