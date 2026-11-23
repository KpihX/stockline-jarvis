"""False-positive measurement of the plausibility warnings over the seed history (offline, no server, no DB write).

    cd apps/backend && uv run python tests/measure_plausibility.py [--seed ../../data/seed] [-v]

Every historical delivered / invoiced order is re-evaluated as if it were a new draft, WITHOUT using itself:
- season_closed, history rule: the client's dates of the OTHER years only (leave-one-year-out: the hardest
  honest setting, the live system also sees the same year's earlier orders). Explicit rule: texts of the client.
- unusual_quantity: (a) leave-one-out = all the client's other orders; (b) chronological = only earlier
  orders, so the first orders of a product (cold start) are included: the upper bound.
A historical order almost never should warn: the rate below is the false-positive rate.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

os.environ["DB_PATH"] = str(Path(tempfile.mkdtemp()) / "measure.db")  # never touch the live ERP database
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import plausibility as pl  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
QTY_TRUST = pl.QTY_MIN_HISTORY


def load(seed: Path, name: str):
    return json.loads((seed / f"{name}.json").read_text("utf-8"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", default=str(REPO / "data" / "seed"))
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    seed = Path(args.seed)
    orders = [o for o in load(seed, "orders") if o["status"] in ("delivered", "invoiced")]
    clients = {c["id"]: c for c in load(seed, "clients")}
    products = {p["id"]: p for p in load(seed, "products")}
    ctx = defaultdict(list)
    for e in load(seed, "contextEntries"):
        if e.get("entityType", e.get("scope")) == "client":
            ctx[e["entityId"]].append(e["body"])
    h = pl.build_history(orders)
    print(f"{len(orders)} delivered/invoiced orders, {len(h.dates)} clients, thresholds: "
          f"season window {pl.SEASON_WINDOW_MIN_DAYS}-{pl.SEASON_WINDOW_MAX_DAYS}d x{pl.SEASON_GAP_FACTOR}, qty x{pl.QTY_P90_FACTOR} p90, never x{pl.QTY_NEVER_ORDERED_FACTOR} p95")  # fmt: skip

    # ── season, history rule ──
    fp, decided, by_client = 0, 0, Counter()
    cache: dict[tuple[str, str], bool] = {}
    for o in orders:
        key = (o["clientId"], o["deliveryDate"])
        if key not in cache:
            others = [d for d in h.dates[o["clientId"]] if d[:4] != o["deliveryDate"][:4]]
            cache[key] = pl.season_closed(o["deliveryDate"], others, None) is not None
        if cache[key]:
            fp += 1
            by_client[o["clientId"]] += 1
    print(f"\nseason_closed (history rule, leave-one-year-out): {fp}/{len(orders)} = {100 * fp / len(orders):.2f} % of historical orders would warn")
    for cid, n in by_client.most_common(8 if not args.verbose else 50):
        print(f"   {cid} {clients[cid]['name']}: {n}")

    # ── season, explicit rule ──
    seasons = {cid: pl.parse_season([c.get("preferences") or "", *(n["text"] for n in c.get("notes") or []), *ctx[cid]]) for cid, c in clients.items()}
    with_season = {cid for cid, s in seasons.items() if s}
    n_ex = sum(1 for o in orders if o["clientId"] in with_season)
    fp_ex = [o for o in orders if o["clientId"] in with_season and seasons[o["clientId"]].is_closed_on(o["deliveryDate"])]
    print(f"\nseason_closed (explicit text): {len(with_season)} clients have a parsable season; {len(fp_ex)}/{n_ex} of their historical orders fall in 'closed' ({100 * len(fp_ex) / max(n_ex, 1):.2f} %)")  # fmt: skip
    for o in fp_ex[:5]:
        print("   ", o["clientId"], o["deliveryDate"], seasons[o["clientId"]].phrase)
    near = sum(1 for o in fp_ex if o["deliveryDate"][5:] <= "12-15" and o["deliveryDate"][5:] >= "12-01" or "04-16" <= o["deliveryDate"][5:] <= "04-30")
    print(f"   {near} of those are in 1-14 Dec / 16-30 Apr: the notes say 'mi-décembre → mi-avril', the orders really run ~1 Dec → 30 Apr (the contradiction is in the data, not in the parser)")  # fmt: skip
    from datetime import date, timedelta

    days = [date(2026, 1, 1) + timedelta(d) for d in range(365)]
    ex_closed = hist_closed = both = 0
    for cid in with_season:
        for d in days:
            e = seasons[cid].is_closed_on(d.isoformat())
            hc = pl.season_closed(d.isoformat(), h.dates.get(cid, []), None) is not None
            ex_closed += e
            hist_closed += hc
            both += e and hc
    print(f"   over the 365 days of 2026 x {len(with_season)} clients: explicit closed {ex_closed} days, history closed {hist_closed}, both {both} ({100 * both / ex_closed:.1f} % of explicit-closed days confirmed by history)")  # fmt: skip

    # ── quantity ──
    per_pair: dict[tuple[str, str], list[tuple[str, float]]] = defaultdict(list)
    for o in orders:
        tot: dict[str, float] = defaultdict(float)
        for l in o["lines"]:
            tot[l["productId"]] += l["qty"]
        for pid, q in tot.items():
            per_pair[(o["clientId"], pid)].append((o["deliveryDate"], q))
    loo, chrono, cold_total, cold_fp, lines = 0, 0, 0, 0, 0
    hit = Counter()  # recall: a historical line multiplied by 4 / 10 (typo-like) must warn
    tried = 0
    samples: list[str] = []
    for (cid, pid), seq in per_pair.items():
        seq.sort()
        unit = products[pid]["unit"]
        vals = [q for _, q in seq]
        for i, (d, q) in enumerate(seq):
            lines += 1
            if pl.unusual_quantity(q, unit, vals[:i] + vals[i + 1 :], h.peers[pid]):
                loo += 1
                if len(samples) < 6:
                    samples.append(f"{cid} {pid} {d}: {q} {unit} vs {sorted(vals[:i] + vals[i + 1:])[-3:]}")
            c = pl.unusual_quantity(q, unit, vals[:i], h.peers[pid])
            chrono += bool(c)
            if i == 0:
                cold_total += 1
                cold_fp += bool(c)
            if len(vals) > QTY_TRUST and q > 0:
                tried += 1
                for mult in (4, 10):
                    hit[mult] += bool(pl.unusual_quantity(q * mult, unit, vals[:i] + vals[i + 1 :], h.peers[pid]))
    print(f"\nunusual_quantity over {lines} (order, product) pairs:")
    print(f"   leave-one-out : {loo} warn = {100 * loo / lines:.3f} %")
    print(f"   chronological : {chrono} warn = {100 * chrono / lines:.3f} % (of which first-ever order of a product: {cold_fp}/{cold_total} = {100 * cold_fp / cold_total:.2f} %)")  # fmt: skip
    for s in samples:
        print("   e.g.", s)
    print(f"   recall on {tried} lines of regulars (>{QTY_TRUST} past orders), the quantity multiplied: x4 → {100 * hit[4] / tried:.1f} % warn, x10 → {100 * hit[10] / tried:.1f} % warn (small lines stay under the unit floor on purpose)")  # fmt: skip

    # ── the live example ──
    q = sorted(h.qty[("cli_0082", "prd_0068")])
    print(f"\ncli_0082 x prd_0068: n={len(q)}, median={q[len(q) // 2]}, p90={pl._pctl(q, 0.9):.0f}, max={q[-1]} → 200 kg warns? {bool(pl.unusual_quantity(200, 'kg', q, h.peers['prd_0068']))}; 800 kg warns? {bool(pl.unusual_quantity(800, 'kg', q, h.peers['prd_0068']))}")  # fmt: skip


if __name__ == "__main__":
    main()
