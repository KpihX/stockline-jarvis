"""AI-helped personalised dashboard synthesis & clickable suggestions per role (client, supplier, manager, admin).

Reads live ERP facts for the verified caller (habits, low-stock alerts on favourite products, active promotions,
open invoices/orders, supplier POs, dormant portfolio clients), builds rich deterministic candidates immediately,
and optionally enriches the greeting/synthesis with the active LLM (bounded 2.5 s, rotated on refresh).
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from app.clients import LLMRequest, LLMText, get_llm_client
from app.policy import Caller
from app.schemas import ChatMessage
from app.tools.erp import ErpClient, ErpError, enc

LLM_SUGGEST_TIMEOUT_S = 6.0
_cache: dict[tuple, tuple[float, dict]] = {}
CACHE_TTL_S = 90.0


def _clip(s: str, n: int) -> str:
    t = " ".join((s or "").split())
    return t if len(t) <= n else t[: n - 1].rstrip() + "…"


async def _erp_get(erp: ErpClient, path: str, params: dict | None = None, default: Any = None) -> Any:
    try:
        return await asyncio.wait_for(erp.get(path, params), 2.5)
    except (ErpError, TimeoutError, Exception):
        return default


def _rotate(items: list[dict], seed: int, keep: int = 4) -> list[dict]:
    if len(items) <= keep:
        return items
    shift = seed % len(items)
    rotated = items[shift:] + items[:shift]
    if seed == 0:
        urgent = [x for x in rotated if x.get("tone") in ("warning", "destructive")]
        others = [x for x in rotated if x.get("tone") not in ("warning", "destructive")]
        return (urgent[:1] + others + urgent[1:])[:keep]
    return rotated[:keep]


async def _llm_polish(role: str, name: str, facts_summary: str, raw_suggestions: list[dict], seed: int) -> str | None:
    """Optional short natural French briefing sentence (<= 6 s, 280 tokens); None on mock/timeout/error."""
    llm = get_llm_client()
    if llm.provider == "mock":
        return None
    sys_prompt = (
        "Tu es l'assistant commercial d'Alpes Restauration (grossiste alimentaire CHR en Isère/Savoie). "
        "Écris UNE synthèse personnelle courte (2 phrases max, français naturel, sans markdown ni puces, sans ID technique) "
        "pour accueillir cet utilisateur sur son tableau de bord et mettre en avant l'opportunité la plus utile."
    )
    user_msg = (
        f"Profil: {role} ({name}). Variation #{seed}.\n"
        f"Faits: {facts_summary}\n"
        f"Pistes: {'; '.join(s['title'] for s in raw_suggestions[:3])}"
    )
    try:
        out = ""
        async def _run():
            nonlocal out
            async for ev in llm.stream(LLMRequest(system=sys_prompt, messages=[ChatMessage(role="user", content=user_msg)], tools=[], max_tokens=280)):
                if isinstance(ev, LLMText):
                    out += ev.delta
        await asyncio.wait_for(_run(), LLM_SUGGEST_TIMEOUT_S)
        cleaned = _clip(out.replace("*", "").replace("#", ""), 320)
        return cleaned if len(cleaned) >= 15 else None
    except Exception:
        return None


async def build_suggestions(caller: Caller, *, seed: int = 0, use_llm: bool = True) -> dict[str, Any]:
    cache_key = (caller.role, caller.client_id, caller.supplier_id, caller.actor_name, seed % 8)
    hit = _cache.get(cache_key)
    if hit and time.monotonic() - hit[0] < CACHE_TTL_S:
        return hit[1]

    erp = ErpClient("ai_chat", caller.erp_name)
    suggestions: list[dict[str, Any]] = []
    headline = ""
    notes_digest: list[str] = []
    ai_generated = False

    if caller.role == "client" and caller.client_id:
        cid = caller.client_id
        client, stock_page, ctx_for, orders_res = await asyncio.gather(
            _erp_get(erp, f"/api/clients/{enc(cid)}", default={}),
            _erp_get(erp, "/api/stock", {"limit": 100}, default={"items": []}),
            _erp_get(erp, "/api/context/for", {"entityType": "client", "id": cid}, default={"entries": []}),
            _erp_get(erp, "/api/orders", {"clientId": cid, "limit": 8}, default=[]),
        )
        cname = client.get("name") or caller.actor_name or "Client"
        fr_days = {"mon": "lun", "tue": "mar", "wed": "mer", "thu": "jeu", "fri": "ven", "sat": "sam", "sun": "dim"}
        days = ", ".join(fr_days.get(d, d) for d in (client.get("deliveryDays") or []))
        usual = list(client.get("usual") or [])
        orders = orders_res if isinstance(orders_res, list) else orders_res.get("items", [])
        # Seasonal clients (e.g. mountain restaurants) have empty 60-day `usual`: derive from their latest delivered/invoiced orders
        if not usual:
            hist_orders = [o for o in orders if o.get("status") in ("delivered", "invoiced", "confirmed")][:3]
            if hist_orders:
                details = await asyncio.gather(*(_erp_get(erp, f"/api/orders/{enc(o['id'])}", default={}) for o in hist_orders))
                agg: dict[str, dict[str, Any]] = {}
                for od in details:
                    for ln in (od or {}).get("lines") or []:
                        pid = ln.get("productId")
                        if not pid:
                            continue
                        cur = agg.setdefault(pid, {"productId": pid, "productName": ln.get("productName", pid), "unit": ln.get("unit", "kg"), "tot": 0.0, "n": 0})
                        cur["tot"] += float(ln.get("qty") or 0)
                        cur["n"] += 1
                usual = [
                    {"productId": v["productId"], "productName": v["productName"], "unit": v["unit"], "avgQty": round(v["tot"] / max(1, v["n"]), 1)}
                    for v in sorted(agg.values(), key=lambda x: -x["n"])[:8]
                ]

        stock_items = stock_page.get("items", []) if isinstance(stock_page, dict) else []
        stock_by_id = {s.get("productId") or (s.get("product") or {}).get("id"): s for s in stock_items}

        # 1) Usual product stock / expiry / promo hooks
        for u in usual[:8]:
            pid = u.get("productId")
            pname = u.get("productName", "produit habituel")
            qty = u.get("avgQty") or u.get("lastQty") or 5
            unit = u.get("unit") or "kg"
            st = stock_by_id.get(pid) or {}
            avail = st.get("available", 999)
            if isinstance(avail, (int, float)) and avail <= 0:
                suggestions.append({
                    "id": f"oos-{pid}",
                    "badge": "Rupture habituelle",
                    "tone": "destructive",
                    "title": f"{_clip(pname, 42)} est en rupture",
                    "reason": "Votre fiche indique une préférence stricte : demandons une alternative adaptée.",
                    "prompt": f"Je vois que {_clip(pname, 40)} est en rupture, quelle alternative me conseillez-vous pour {cname} ?",
                    "targetSurface": "voice",
                })
            elif isinstance(avail, (int, float)) and avail < max(30, qty * 2):
                suggestions.append({
                    "id": f"low-{pid}",
                    "badge": "Stock limité",
                    "tone": "warning",
                    "title": f"Réserver {_clip(pname, 36)} ({int(avail)} {unit} restants)",
                    "reason": f"Vous en commandez ~{qty:g} {unit} en moyenne : le stock baisse rapidement.",
                    "prompt": f"Prépare-moi {qty:g} {unit} de {_clip(pname, 40)} avant que le stock ne tombe à zéro.",
                    "targetSurface": "voice",
                })

        # 2) Usual basket ("comme d'hab")
        if usual:
            top3 = ", ".join(_clip(u["productName"], 26) for u in usual[:3])
            suggestions.append({
                "id": "usual-basket",
                "badge": "Comme d'habitude",
                "tone": "emerald",
                "title": f"Renouveler votre panier habituel ({len(usual)} articles)",
                "reason": f"Inclut : {top3}. Prix négociés appliqués automatiquement.",
                "prompt": f"Bonjour, c'est {cname}, je voudrais commander comme d'habitude pour ma prochaine tournée.",
                "targetSurface": "voice",
            })

        # 3) Active promotions / seasonal / Beaufort/raclette context notes
        promo_rows, low_rows = await asyncio.gather(
            _erp_get(erp, "/api/context", {"q": "promo", "limit": 4}, default=[]),
            _erp_get(erp, "/api/stock", {"tab": "out", "limit": 4}, default={"items": []}),
        )
        for pr in (promo_rows if isinstance(promo_rows, list) else [])[:2]:
            if pr.get("kind") in ("pricing", "fact", "preference", "policy"):
                suggestions.append({
                    "id": f"promo-{pr.get('id')}",
                    "badge": "Opportunité",
                    "tone": "violet",
                    "title": _clip(pr.get("title", "Offre en cours"), 52),
                    "reason": _clip(pr.get("body", ""), 110),
                    "prompt": f"Parle-moi de « {_clip(pr.get('title', ''), 48)} » et vérifie si ça s'applique à {cname}.",
                    "targetSurface": "chat",
                })
        oos_items = low_rows.get("items", []) if isinstance(low_rows, dict) else []
        if oos_items and len(suggestions) < 4:
            p_oos = (oos_items[0].get("product") or {}).get("name") or "Beaufort"
            suggestions.append({
                "id": "season-alt",
                "badge": "Info arrivage",
                "tone": "warning",
                "title": f"Rupture sur {_clip(p_oos, 38)} : voir les remplaçants",
                "reason": "Votre commercial propose des alternatives adaptées à votre carte.",
                "prompt": f"Avez-vous du {_clip(p_oos, 36)} ou une bonne alternative disponible pour ma prochaine livraison ?",
                "targetSurface": "voice",
            })

        # 4) Always enrich to at least 5-6 varied candidates so refresh (`seed`) genuinely rotates fresh ideas
        drafts = [o for o in orders if o.get("status") == "draft"]
        if drafts:
            d0 = drafts[0]
            suggestions.append({
                "id": f"draft-{d0['id']}",
                "badge": "Brouillon en attente",
                "tone": "warning",
                "title": f"Finaliser {d0.get('number', 'votre brouillon')} ({d0.get('deliveryDate', '')})",
                "reason": "Relisez les lignes et confirmez avant la clôture de tournée.",
                "prompt": f"Fais-moi le récapitulatif de ma commande brouillon {d0.get('number')} pour que je confirme.",
                "targetSurface": "voice",
            })
        suggestions.extend([
            {
                "id": "cli-tariff",
                "badge": "Tarifs négociés",
                "tone": "violet",
                "title": "Vérifier vos remises volume sur vos produits phares",
                "reason": "Consultez vos paliers (ex. -3 % dès 100 kg) avant de commander.",
                "prompt": f"Quels sont mes tarifs actuels et paliers de remise sur mes produits habituels pour {cname} ?",
                "targetSurface": "chat",
            },
            {
                "id": "cli-season",
                "badge": "Ouverture & tournée",
                "tone": "emerald",
                "title": f"Préparer votre prochaine livraison ({days or 'tournée'})",
                "reason": "Vérifiez les créneaux disponibles et anticipez les produits de saison.",
                "prompt": f"Quels sont les prochains jours de livraison disponibles pour {cname} et quelles sont les arrivées de la semaine ?",
                "targetSurface": "voice",
            },
            {
                "id": "cli-followup",
                "badge": "Suivi commercial",
                "tone": "warning",
                "title": "Revoir vos dernières notes et demandes avec votre commercial",
                "reason": "Faites le point sur vos préférences (zéro substitution) et retours récents.",
                "prompt": f"Résume les derniers échanges et préférences enregistrées sur la fiche de {cname}.",
                "targetSurface": "chat",
            },
            {
                "id": "cli-invoices",
                "badge": "Facturation",
                "tone": "violet",
                "title": "Faire le point sur vos factures et échéances",
                "reason": "Consultez votre encours et vos conditions de règlement en un clic.",
                "prompt": f"Quel est l'état de mes factures ouvertes et de mon encours pour {cname} ?",
                "targetSurface": "chat",
            },
        ])

        # Notes digest (exclude internal/vocab rows)
        for e in (ctx_for.get("entries") or []):
            if e.get("kind") in ("preference", "logistics") and "vocab" not in (e.get("tags") or []):
                notes_digest.append(f"{e.get('title')} : {_clip(e.get('body', ''), 120)}")
        if client.get("preferences"):
            notes_digest.insert(0, f"Préférence ERP : {_clip(client['preferences'], 140)}")

        headline = f"Bonjour {cname}. Vos livraisons passent {days or 'selon tournée'} ; {len(usual)} produits suivis dans vos habitudes."
        facts_summary = f"Livraisons={days}, produits habituels={len(usual)}, notes={'; '.join(notes_digest[:2])}"
        suggestions = _rotate(suggestions, seed, keep=4)
        if use_llm and suggestions:
            polished = await _llm_polish("client", cname, facts_summary, suggestions, seed)
            if polished:
                headline, ai_generated = polished, True
        usual_out = [{"productId": u["productId"], "productName": u["productName"], "qty": u.get("avgQty") or u.get("lastQty") or 1, "unit": u.get("unit", "kg")} for u in usual[:8]]

    elif caller.role == "supplier" and caller.supplier_id:
        sid = caller.supplier_id
        sup, pos_res, low_page = await asyncio.gather(
            _erp_get(erp, f"/api/suppliers/{enc(sid)}", default={}),
            _erp_get(erp, "/api/purchase-orders", {"supplierId": sid, "limit": 12}, default={"items": []}),
            _erp_get(erp, "/api/stock", {"tab": "low", "limit": 30}, default={"items": []}),
        )
        sname = sup.get("name") or caller.actor_name or "Fournisseur"
        pos = pos_res.get("items", []) if isinstance(pos_res, dict) else pos_res
        open_pos = [p for p in pos if p.get("status") in ("sent", "partially_received")]
        if open_pos:
            p0 = open_pos[0]
            suggestions.append({
                "id": f"po-{p0['id']}",
                "badge": "Livraison attendue",
                "tone": "violet",
                "title": f"Suivre l'achat {p0.get('number')} (prévu {p0.get('expectedDate', '?')})",
                "reason": "Confirmez la fenêtre d'arrivée ou signalez un éventuel reliquat.",
                "prompt": f"Consulte notre fiche fournisseur {sname} et fais le point sur nos livraisons attendues.",
                "targetSurface": "voice",
            })
        suggestions.extend([
            {
                "id": "sup-stock",
                "badge": "Réapprovisionnement",
                "tone": "emerald",
                "title": "Vérifier nos niveaux de stock chez Alpes Restauration",
                "reason": "Anticipez les besoins avant la préparation nocturne.",
                "prompt": f"Quels produits ont un stock bas ou en rupture chez Alpes Restauration en ce moment ?",
                "targetSurface": "chat",
            },
            {
                "id": "sup-event",
                "badge": "Signalement rapide",
                "tone": "warning",
                "title": "Signaler un retard, un lot court ou une mise à jour tarif",
                "reason": "Enregistrement direct sur votre fiche fournisseur.",
                "prompt": f"Je veux signaler une livraison partielle prévue demain matin pour {sname}.",
                "targetSurface": "voice",
            },
            {
                "id": "sup-history",
                "badge": "Qualité & litiges",
                "tone": "violet",
                "title": "Consulter l'historique de réceptions et incidents",
                "reason": "Relisez les derniers retours enregistrés sur votre fiche.",
                "prompt": f"Résume les derniers événements qualité et livraisons incomplètes de {sname}.",
                "targetSurface": "chat",
            },
            {
                "id": "sup-slot",
                "badge": "Quai de réception",
                "tone": "emerald",
                "title": "Confirmer votre créneau de livraison nuit / matin",
                "reason": "Évitez l'attente à quai entre 3 h et 6 h à Grenoble.",
                "prompt": f"Bonjour, c'est {sname}, je veux confirmer l'horaire d'arrivée de notre prochaine livraison.",
                "targetSurface": "voice",
            },
        ])
        for ev in (sup.get("recentEvents") or [])[:3]:
            notes_digest.append(f"{ev.get('at', '')[:10]} · {ev.get('title', '')}")
        headline = f"Bienvenue {sname}. Vous avez {len(open_pos)} bon(s) d'achat en cours avec Alpes Restauration."
        suggestions = _rotate(suggestions, seed, keep=4)
        if use_llm and suggestions:
            polished = await _llm_polish("fournisseur", sname, f"POs ouverts={len(open_pos)}", suggestions, seed)
            if polished:
                headline, ai_generated = polished, True

    else:
        # manager or admin (or unknown fallback)
        dash, low_page, drafts_page = await asyncio.gather(
            _erp_get(erp, "/api/dashboard", default={}),
            _erp_get(erp, "/api/stock", {"tab": "out", "limit": 10}, default={"items": []}),
            _erp_get(erp, "/api/orders", {"status": "draft", "limit": 8}, default=[]),
        )
        drafts = drafts_page if isinstance(drafts_page, list) else drafts_page.get("items", [])
        oos = low_page.get("items", []) if isinstance(low_page, dict) else []
        if drafts:
            suggestions.append({
                "id": "mgr-drafts",
                "badge": "À confirmer",
                "tone": "violet",
                "title": f"{len(drafts)} pré-commande(s) brouillon à valider",
                "reason": f"Dont {drafts[0].get('clientName', 'client')} ({drafts[0].get('number')}).",
                "prompt": f"Résume les pré-commandes en brouillon et vérifie les alertes sur {drafts[0].get('number')}.",
                "targetSurface": "chat",
            })
        if oos:
            p0 = (oos[0].get("product") or {}).get("name") or "un produit phare"
            suggestions.append({
                "id": "mgr-oos",
                "badge": "Rupture critique",
                "tone": "destructive",
                "title": f"{len(oos)} rupture(s) détectée(s) (ex. {_clip(p0, 32)})",
                "reason": "Trouvez les meilleures alternatives en stock avant les appels du matin.",
                "prompt": f"Quelles alternatives en stock avons-nous pour {_clip(p0, 36)} et qui en commande d'habitude ?",
                "targetSurface": "voice",
            })
        if dash.get("overdueInvoicesCount"):
            suggestions.append({
                "id": "mgr-overdue",
                "badge": "Finance",
                "tone": "warning",
                "title": f"{dash['overdueInvoicesCount']} facture(s) en retard à relancer",
                "reason": f"Total en retard : {round(dash.get('overdueInvoicesAmount', 0)):,} €.".replace(",", " "),
                "prompt": "Liste les clients prioritaires ayant des factures en retard avant d'accepter de nouvelles commandes.",
                "targetSurface": "chat",
            })
        suggestions.extend([
            {
                "id": "mgr-payet",
                "badge": "Simulation appel",
                "tone": "emerald",
                "title": "Tester un appel difficile (Le Refuge Payet · hors saison)",
                "reason": "Démonstration des alertes backend season_closed + résolveur phonétique.",
                "prompt": "Prends une commande pour Le Refuge Payet : 200 kilos de frites pour le 1er décembre.",
                "targetSurface": "voice",
            },
            {
                "id": "mgr-routes",
                "badge": "Tournées du matin",
                "tone": "violet",
                "title": "Préparer les tournées Oisans & Vercors de demain",
                "reason": "Contrôlez les commandes confirmées avant la clôture logistique.",
                "prompt": "Fais le point sur les livraisons prévues demain et les tournées les plus chargées.",
                "targetSurface": "chat",
            },
            {
                "id": "mgr-expiry",
                "badge": "DLC & lots FEFO",
                "tone": "warning",
                "title": "Repérer les lots frais à écouler en priorité",
                "reason": "Proposez des remises ciblées aux clients habituels avant perte.",
                "prompt": "Quels lots arrivent bientôt à expiration et à quels clients les proposer ?",
                "targetSurface": "chat",
            },
            {
                "id": "mgr-vip",
                "badge": "Reprise saison",
                "tone": "emerald",
                "title": "Relancer les stations avant le pic de décembre",
                "reason": "Vérifiez les préférences et tarifs des clients montagne actifs.",
                "prompt": "Quels clients de montagne ont une préférence particulière pour la reprise de saison ?",
                "targetSurface": "voice",
            },
        ])
        name = caller.actor_name or ("Direction" if caller.role == "admin" else "Équipe commerciale")
        headline = f"Bonjour {name}. {len(drafts)} brouillon(s) en attente et {len(oos)} rupture(s) active(s) ce matin."
        suggestions = _rotate(suggestions, seed, keep=4)
        if use_llm and suggestions:
            polished = await _llm_polish(caller.role, name, f"brouillons={len(drafts)}, ruptures={len(oos)}", suggestions, seed)
            if polished:
                headline, ai_generated = polished, True

    result = {
        "role": caller.role,
        "headline": headline,
        "aiGenerated": ai_generated,
        "notesDigest": notes_digest[:4],
        "usualProducts": locals().get("usual_out", []),
        "suggestions": suggestions,
        "seed": seed,
    }
    _cache[cache_key] = (time.monotonic(), result)
    return result
