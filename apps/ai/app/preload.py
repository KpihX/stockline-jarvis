"""
Client sheet preloaded at identification: the end of the system prompt already holds what the agent would otherwise fetch with
search → get_client → get_context (1-2 LLM round-trips saved per call).

    client_sheet(caller)   "" or a compact French block (≤ ~800 tokens) about caller.client_id
    build_sheet(...)       pure: ERP payloads → text, per role (a client does not get credit figures, the reps' notes or risk cards)

Fetched from the ERP (GET /api/clients/{id}, GET /api/context/for), cached SHEET_TTL_S per (client, role scope) so a burst of calls
costs one fetch. The voice session freezes the resulting text for the whole conversation (a changing prompt tail = a cache miss).
Never raises, never stalls a turn for long: no ERP → no sheet, and the tools are still there.
"""

import asyncio
import time

from app.config import env
from app.policy import Caller
from app.tools.erp import ErpClient, ErpError, enc

ENABLED = env("IDENTITY_PRELOAD", "1") != "0"  # measurement knob (README): 0 = no sheet, the agent fetches the client itself
SHEET_TTL_S = 300
SHEET_TIMEOUT_S = 3.0
MAX_CHARS = 3200  # ≈ 800 tokens
DAYS = {"mon": "lun", "tue": "mar", "wed": "mer", "thu": "jeu", "fri": "ven", "sat": "sam", "sun": "dim"}
CONTEXT_KINDS = {"client": ("preference", "logistics", "procedure"), "internal": ("preference", "logistics", "procedure", "pricing", "relationship")}

_cache: dict[tuple[str, str], tuple[float, str]] = {}


def clip(s: str, n: int) -> str:
    s = " ".join((s or "").split())
    return f"{s[: n - 1]}…" if len(s) > n else s


def num(x) -> str:
    return f"{x:g}" if isinstance(x, (int, float)) else str(x)


def build_sheet(client: dict, context: dict | None, role: str) -> str:
    """The sheet as text. `role`: client | sales | direction. A client's sheet leaves out credit figures, the reps' notes and risk / policy cards."""
    internal = role != "client"
    days = ", ".join(DAYS.get(d, d) for d in client.get("deliveryDays") or [])
    lines = [
        "# Fiche client préchargée (ERP, lue au début de l'appel : ne la relis pas avec get_client / get_context sauf pour un détail absent)",
        f"- {client['name']} ({client['id']}) : {client.get('type', '?')}, {client.get('city', '?')}, zone {client.get('zone', '?')}, statut {client.get('status', '?')}."
        + (" COMPTE BLOQUÉ : ne prends aucune commande, passe le relais au commercial." if client.get("status") == "blocked" else ""),
        f"- Livraison : {days or '?'}. Paiement : {num(client.get('paymentTermsDays', '?'))} jours.",
    ]
    if internal:
        lines.append(f"- Crédit : plafond {num(client.get('creditLimit', '?'))} €, encours {num(client.get('outstanding', 0))} €, en retard {num(client.get('overdue', 0))} €.")
    if client.get("preferences"):
        lines.append(f"- Préférences : {clip(client['preferences'], 260)}")
    if client.get("openIssues"):
        lines.append(f"- Dossiers ouverts : {client['openIssues']}.")
    usual = (client.get("usual") or [])[:8]
    if usual:
        lines.append("- Habitudes (60 j, quantité moyenne) : " + " ; ".join(f"{clip(u['productName'], 45)} [{u['productId']}] {num(u['avgQty'])} {u.get('unit', '')}" for u in usual))
    events = (client.get("recentEvents") or [])[:5]
    if events:
        lines.append("- Derniers événements : " + " ; ".join(f"{e['at'][:10]} {e['type']} « {clip(e['title'], 80)} »" for e in events))
    if internal and client.get("notes"):
        n = client["notes"][-1]
        lines.append(f"- Dernière note commerciale ({n['at'][:10]}) : {clip(n['text'], 160)}")
    kinds = CONTEXT_KINDS["internal" if internal else "client"]  # a client's list leaves out risk / policy / pricing cards
    for e in (context or {}).get("entries", []):
        if e.get("kind") in kinds:
            lines.append(f"- {e['title']} : {clip(e['body'], 200)}")
    text = "\n".join(lines)
    return text if len(text) <= MAX_CHARS else text[: MAX_CHARS - 1] + "…"


async def client_sheet(caller: Caller) -> str:
    """The sheet of caller.client_id for this role ("" for unknown callers, a commercial without a client, or when the ERP does not answer)."""
    if not ENABLED or not caller.client_id or caller.role == "unknown":
        return ""
    key = (caller.client_id, "client" if caller.role == "client" else "internal")
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < SHEET_TTL_S:
        return hit[1]
    erp = ErpClient("voice_agent", caller.erp_name)
    try:
        client, context = await asyncio.wait_for(
            asyncio.gather(erp.get(f"/api/clients/{enc(caller.client_id)}"), erp.get("/api/context/for", {"entityType": "client", "id": caller.client_id})),
            SHEET_TIMEOUT_S,
        )
    except (ErpError, TimeoutError, KeyError, ValueError) as e:
        print(f"[preload] fiche {caller.client_id} indisponible ({type(e).__name__}: {e})", flush=True)
        return ""
    text = build_sheet(client, context, caller.role)
    _cache[key] = (time.monotonic(), text)
    return text


def invalidate(client_id: str | None = None) -> None:
    for key in [k for k in _cache if client_id in (None, k[0])]:
        del _cache[key]
