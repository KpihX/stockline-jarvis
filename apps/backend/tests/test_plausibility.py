"""Table-driven tests of the `season_closed` and `unusual_quantity` order warnings.

Pure logic first (no database), then the same warnings through the API on the seed (skipped without a seed).
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.services import plausibility as pl


def every(step: int, start: str, end: str) -> list[str]:
    d, stop, out = date.fromisoformat(start), date.fromisoformat(end), []
    while d <= stop:
        out.append(d.isoformat())
        d += timedelta(days=step)
    return out


# A station restaurant: ordered every 3 days from 15 Dec to 30 Apr in three seasons (2023-24, 2024-25, 2025-26).
SEASONAL = sorted(d for y in (2023, 2024, 2025) for d in every(3, f"{y}-12-15", f"{y + 1}-04-30"))
YEAR_ROUND = every(2, "2023-11-25", "2026-11-20")
ONE_SEASON = every(3, "2025-12-15", "2026-04-30")  # only one season of history

# ───────── season_closed, from the order history ─────────


@pytest.mark.parametrize(
    "target, closed",
    [
        ("2026-07-15", True),  # deep off-season
        ("2026-11-24", True),
        ("2027-02-10", False),  # mid-season
        ("2026-12-20", False),
        ("2026-12-06", True),  # window (±8 d) still ends before the first order of the season (15 Dec)…
        ("2026-12-07", False),  # …one day later it reaches it: open (benefit of the doubt on the boundary)
        ("2027-05-05", False),  # window still reaches the last orders of April
        ("2027-05-10", True),
        ("2028-02-29", False),  # leap day does not crash
    ],
)
def test_season_from_history(target, closed):
    assert (pl.season_closed(target, SEASONAL, None) is not None) is closed


def test_season_history_cites_the_years():
    v = pl.season_closed("2026-12-01", SEASONAL, None)
    assert v and v.source == "historique" and v.years == (2024, 2025)  # 2023 starts after the window, tells nothing


@pytest.mark.parametrize(
    "dates, target",
    [
        ([], "2026-07-15"),  # no history
        (SEASONAL[:8], "2026-07-15"),  # fewer than SEASON_MIN_ORDERS orders
        (ONE_SEASON, "2026-07-15"),  # a single season: the window is observed only once
        (YEAR_ROUND, "2026-08-15"),  # year-round client: never closed
        (YEAR_ROUND, "2027-03-03"),
    ],
)
def test_season_no_verdict(dates, target):
    assert pl.season_closed(target, dates, None) is None


# ───────── season_closed, from an explicit text ─────────

OPEN_TXT = "Station : ouvert de mi-décembre à mi-avril, zéro commande le reste de l'année."
CLOSED_TXT = "Fermé en mai-juin et de septembre à mi-décembre."


@pytest.mark.parametrize(
    "text, day, closed",
    [
        (OPEN_TXT, "2026-12-01", True),
        (OPEN_TXT, "2026-12-14", True),
        (OPEN_TXT, "2026-12-15", False),  # the 15th of a "mi-" is never flagged
        (OPEN_TXT, "2027-01-12", False),
        (OPEN_TXT, "2027-04-15", False),
        (OPEN_TXT, "2027-04-16", True),
        (OPEN_TXT, "2027-07-01", True),
        (CLOSED_TXT, "2027-05-01", True),
        (CLOSED_TXT, "2027-06-30", True),
        (CLOSED_TXT, "2027-07-01", False),
        (CLOSED_TXT, "2027-08-31", False),
        (CLOSED_TXT, "2026-09-01", True),
        (CLOSED_TXT, "2026-12-14", True),
        (CLOSED_TXT, "2026-12-15", False),
        (CLOSED_TXT, "2027-01-10", False),
    ],
)
def test_explicit_season(text, day, closed):
    season = pl.parse_season(["Paie par chèque.", text])
    assert season is not None
    assert (pl.season_closed(day, [], season) is not None) is closed


@pytest.mark.parametrize(
    "text",
    [
        "Fermé pendant les vacances scolaires.",
        "Réouverture le 12/12 pour un séminaire, puis saison à partir du 19/12.",
        "La ferme de Paul livre en mai.",
        "Commande le soir après le service vers 22h.",
        "",
    ],
)
def test_parse_season_ignores_other_texts(text):
    assert pl.parse_season([text]) is None


def test_explicit_season_wins_and_shows_the_contradiction():
    season = pl.parse_season([OPEN_TXT])
    v = pl.season_closed("2026-12-01", SEASONAL, season)  # history says: no order before 15 Dec either → no years
    assert v and v.source == "fiche" and v.years == ()
    early = sorted(SEASONAL + every(3, "2024-12-01", "2024-12-14") + every(3, "2025-12-01", "2025-12-14"))
    v = pl.season_closed("2026-12-01", early, season)  # history says: this client did order on 1 Dec
    assert v and v.source == "fiche" and v.years == (2024, 2025)
    assert "pourtant commandé" in pl.season_message("Le Refuge", "2026-12-01", v)


def test_season_messages_are_french_and_id_free():
    hist = pl.season_message("Le Refuge Payet", "2026-12-01", pl.season_closed("2026-12-01", SEASONAL, None))
    assert hist == "Livraison le 1er décembre : Le Refuge Payet semble fermé à cette période, aucune commande à cette date en 2024 et 2025"
    fiche = pl.season_message("Le Refuge Payet", "2026-12-03", pl.season_closed("2026-12-03", [], pl.parse_season([OPEN_TXT])))
    assert fiche == "Livraison le 3 décembre : Le Refuge Payet est ouvert de mi-décembre à mi-avril seulement"


# ───────── unusual_quantity ─────────

REGULAR = [88, 93, 96, 102.5, 106.5, 113.5, 119.5, 124, 131.5, 157.5, 172, 200]  # a big fries client (kg)
PEERS = [float(x) for x in range(10, 210, 2)]  # 100 lines from 10 to 208 kg: p95 ≈ 200


@pytest.mark.parametrize(
    "qty, unit, past, peers, warns",
    [
        (200, "kg", REGULAR, PEERS, False),  # the client's own record: no false positive on its usual volumes
        (330, "kg", REGULAR, PEERS, False),
        (400, "kg", REGULAR, PEERS, False),
        (500, "kg", REGULAR, PEERS, True),  # > 2.5 × p90 (≈ 450)
        (8, "kg", [1, 1, 2, 1, 1, 2], None, False),  # far above history but under the unit floor: a small order never warns
        (25, "kg", [1, 1, 2, 1, 1, 2], None, False),  # exactly the floor
        (26, "kg", [1, 1, 2, 1, 1, 2], None, True),
        (12, "box", [1] * 6, None, True),  # box floor is 10
        (10, "box", [1] * 6, None, False),
        (40, "kg", [10, 12], None, True),  # short history (< 5 orders): reference is the max (12) → limit 2.5 × 12 = 30
        (30, "kg", [10, 12], None, False),
        (200, "kg", [], PEERS, False),  # never ordered, inside what clients take
        (300, "kg", [], PEERS, True),  # never ordered, far above
        (300, "kg", [], PEERS[:10], False),  # product too rare to judge
        (300, "kg", [], None, False),  # no reference at all
    ],
)
def test_unusual_quantity(qty, unit, past, peers, warns):
    assert (pl.unusual_quantity(qty, unit, past, peers) is not None) is warns


def test_unusual_quantity_message():
    v = pl.unusual_quantity(400, "kg", [8, 8, 8, 9, 8, 8], None)
    assert v and not v.never_ordered
    assert pl.quantity_message("Frites surgelées 9 mm (carton 4 × 2,5 kg)", "kg", 400, v) == "Frites surgelées 9 mm : le client en commande en général 8 kg, la ligne en fait 400"
    n = pl.unusual_quantity(300, "kg", [], PEERS)
    assert n and n.never_ordered
    msg = pl.quantity_message("Raclette tranchée", "kg", 300, n)
    assert "n'en a jamais commandé" in msg and "300 kg" in msg and "moins de 200" in msg
    assert "prd_" not in msg and "cli_" not in msg


# ───────── History index ─────────


def test_history_counts_only_delivered_and_invoiced():
    def order(status, d, qty):
        return {"clientId": "c1", "status": status, "deliveryDate": d, "lines": [{"productId": "p1", "qty": qty}, {"productId": "p1", "qty": 1}]}

    h = pl.build_history([order("invoiced", "2025-01-02", 5), order("delivered", "2025-01-09", 6), order("draft", "2025-01-10", 999),
                          order("confirmed", "2025-01-11", 999), order("cancelled", "2025-01-12", 999)])  # fmt: skip
    assert h.dates == {"c1": ["2025-01-02", "2025-01-09"]}
    assert h.qty[("c1", "p1")] == [6, 7]  # lines of the same product in one order add up
    assert h.peers["p1"] == [6, 7]


# ───────── Through the API, on the seed ─────────


@pytest.fixture(scope="module")
def api():
    from fastapi.testclient import TestClient

    from app.core.config import SEED_DIR

    if not (SEED_DIR / "meta.json").exists():
        pytest.skip("no seed in DATA_DIR/seed")
    from app.main import app

    with TestClient(app) as c:
        yield c


def codes(order: dict) -> dict[str, str]:
    return {w["code"]: w["message"] for w in order["warnings"]}


def test_api_refuge_payet(api):
    """The live case: 200 kg of fries on 1 Dec for a client open mid-December to mid-April."""
    r = api.post("/api/orders", json={"clientId": "cli_0082", "deliveryDate": "2026-12-01", "lines": [{"productId": "prd_0068", "qty": 200}]})
    assert r.status_code == 201, r.text
    order = r.json()
    w = codes(order)
    assert "season_closed" in w and "Le Refuge Payet" in w["season_closed"] and "mi-décembre" in w["season_closed"]
    assert "unusual_quantity" not in w  # 200 kg is within this client's record (median 108, max 330)
    assert all(x["code"] != "season_closed" or "productId" not in x for x in order["warnings"])

    oid = order["id"]
    w = codes(api.patch(f"/api/orders/{oid}", json={"deliveryDate": "2027-01-12"}).json())  # in season
    assert "season_closed" not in w
    w = codes(api.patch(f"/api/orders/{oid}", json={"deliveryDate": "2027-07-13"}).json())  # off season again
    assert "season_closed" in w

    line = api.get(f"/api/orders/{oid}").json()["lines"][0]["id"]
    w = codes(api.patch(f"/api/orders/{oid}/lines/{line}", json={"qty": 900}).json())
    assert "unusual_quantity" in w and "en général" in w["unusual_quantity"] and "900" in w["unusual_quantity"]
    w = codes(api.patch(f"/api/orders/{oid}/lines/{line}", json={"qty": 40}).json())
    assert "unusual_quantity" not in w

    confirmed = api.post(f"/api/orders/{oid}/confirm").json()  # re-evaluated on confirm; never blocking
    assert confirmed["status"] == "confirmed" and "season_closed" in codes(confirmed)
    assert api.post(f"/api/orders/{oid}/cancel").json()["status"] == "cancelled"


def test_api_new_product_for_a_client(api):
    r = api.post("/api/orders", json={"clientId": "cli_0082", "deliveryDate": "2027-01-12", "lines": [{"productId": "prd_0001", "qty": 1}]}).json()
    assert "unusual_quantity" not in codes(r)
    api.post(f"/api/orders/{r['id']}/cancel")


# ───────── False positives on the seed history (full numbers: `uv run python tests/measure_plausibility.py`) ─────────


def test_seed_history_almost_never_warns():
    import json
    from collections import defaultdict

    from app.core.config import SEED_DIR

    if not (SEED_DIR / "orders.json").exists():
        pytest.skip("no seed")
    orders = [o for o in json.loads((SEED_DIR / "orders.json").read_text("utf-8")) if o["status"] in pl.HISTORY_STATUSES]
    unit = {p["id"]: p["unit"] for p in json.loads((SEED_DIR / "products.json").read_text("utf-8"))}
    h = pl.build_history(orders)
    # quantities: every other order of the client as reference (leave-one-out)
    lines = fp = 0
    for (cid, pid), vals in h.qty.items():
        for i, q in enumerate(vals):
            lines += 1
            fp += pl.unusual_quantity(q, unit[pid], vals[:i] + vals[i + 1 :], h.peers[pid]) is not None
    assert fp / lines < 0.0005, (fp, lines)
    # seasons: every 10th delivery, the client's OTHER years only
    seen, total, fp = defaultdict(int), 0, 0
    for o in orders:
        seen[o["clientId"]] += 1
        if seen[o["clientId"]] % 10:
            continue
        others = [d for d in h.dates[o["clientId"]] if d[:4] != o["deliveryDate"][:4]]
        total += 1
        fp += pl.season_closed(o["deliveryDate"], others, None) is not None
    assert fp / total < 0.005, (fp, total)
