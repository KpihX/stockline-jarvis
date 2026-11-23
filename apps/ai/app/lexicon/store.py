"""
The lexicon as the voice session sees it: ERP reads (cached), learning, forgetting, pruning. Failure tolerant on the read path:
no ERP / no learned data → the lexicon is just smaller, never an error.

    store.catalogue()        global: clients, products + aliases, jargon                  cache CATALOGUE_TTL_S
    store.learned()          every learned row (client-scoped and global)                 cache LEARNED_TTL_S
    store.indexes(client)    [catalogue index, global learned index, client index] + the client's usual products
    store.client_terms(cid)  STT terms for a known caller (best first)
    store.learn(erp, …)      record a CONFIRMED lesson (the evidence was already checked by lexicon/guard.py)
    store.forget(erp, id)    delete a lesson (the context row)
    store.prune(erp)         delete the expired lessons

State is in the ERP context table (lexicon/learned.py documents the row convention), so it survives an AI-service reload;
only the caches are in memory (a learn / forget drops them at once, a `make reset` is noticed within LEARNED_TTL_S or by POST /vocab/refresh).
"""

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date

from app.tools.erp import ErpClient, ErpError

from . import config as cfg
from . import learned as L
from .catalogue import Catalogue, ClientLexicon, build_catalogue, build_client, short_name
from .resolver import Entry, Index, Usual


@dataclass
class Indexes:
    """Everything `resolve()` needs for one turn."""

    indexes: list[Index]
    usual: dict[str, Usual]
    scope: str | None


class _Cached:
    """One value, refreshed after a TTL, never fetched twice at once; on failure the previous value (or `default`) is kept."""

    def __init__(self, ttl: float, load: Callable[[], Awaitable], default):
        self.ttl, self.load, self.value, self.expires = ttl, load, default, 0.0
        self.lock = asyncio.Lock()
        self.loaded = False

    async def get(self):
        async with self.lock:
            if time.monotonic() >= self.expires:
                try:
                    self.value, self.loaded = await asyncio.wait_for(self.load(), 4), True
                    self.expires = time.monotonic() + self.ttl
                except Exception as e:  # ERP down, other shape: keep what we have, retry soon
                    print(f"[lexicon] ERP read failed ({type(e).__name__}: {e}); retry in 30 s", flush=True)
                    self.expires = time.monotonic() + 30
            return self.value

    def drop(self) -> None:
        self.expires = 0.0


class LexiconStore:
    def __init__(self, erp: Callable[[], ErpClient] = lambda: ErpClient("voice_agent")):
        self._erp = erp
        self._catalogue = _Cached(cfg.CATALOGUE_TTL_S, self._load_catalogue, None)
        self._learned = _Cached(cfg.LEARNED_TTL_S, self._load_learned, [])
        self._global_learned: tuple[int, Index] = (-1, Index())
        self._clients: dict[str, tuple[float, ClientLexicon]] = {}
        self._inflight: dict[str, asyncio.Future] = {}
        self._today = ("", 0.0)

    # ── reads ──

    async def _load_catalogue(self) -> Catalogue:
        erp = self._erp()
        products, clients = await asyncio.gather(erp.get("/api/products", {"limit": 500}), erp.get("/api/clients", {"limit": 500}))
        return build_catalogue(products, clients)

    async def _load_learned(self) -> list[L.Learned]:
        erp, out, offset = self._erp(), [], 0
        while True:
            rows = await erp.get("/api/context", {"tag": cfg.VOCAB_TAG, "limit": 500, "offset": offset})
            out += [d for r in rows if (d := L.decode(r))]
            if len(rows) < 500:
                return out
            offset += 500

    async def catalogue(self) -> Catalogue | None:
        return await self._catalogue.get()

    async def today(self) -> str:
        """The business date (GET /api/meta), cached; the machine date when the ERP does not answer."""
        value, at = self._today
        if value and time.monotonic() - at < 300:
            return value
        try:
            value = (await asyncio.wait_for(self._erp().get("/api/meta"), 2))["today"]
        except Exception:
            value = date.today().isoformat()
        self._today = (value, time.monotonic())
        return value

    async def learned(self, include_expired: bool = False) -> list[L.Learned]:
        rows = await self._learned.get()
        if include_expired:
            return list(rows)
        today = await self.today()
        return [r for r in rows if not L.expired(r, today)]

    async def ready(self, wait: float) -> bool:
        """True when the catalogue is loaded (waits at most `wait` seconds): lets a turn skip the resolver rather than stall."""
        if self._catalogue.loaded and time.monotonic() < self._catalogue.expires:
            return True
        try:
            return (await asyncio.wait_for(self._catalogue.get(), wait)) is not None
        except TimeoutError:
            return False

    async def client(self, client_id: str) -> ClientLexicon | None:
        cached = self._clients.get(client_id)
        if cached and time.monotonic() < cached[0]:
            return cached[1]
        return await asyncio.shield(self._start(client_id))  # shielded: a caller that gives up waiting does not cancel the fetch

    def _start(self, client_id: str) -> asyncio.Future:
        task = self._inflight.get(client_id)
        if task is None:
            task = self._inflight[client_id] = asyncio.ensure_future(self._build_client(client_id, self._clients.get(client_id)))
            task.add_done_callback(lambda _t: self._inflight.pop(client_id, None))
        return task

    def prefetch(self, client_id: str) -> None:
        """Warm a caller's lexicon in the background (called when the caller is identified, before their next utterance)."""
        cached = self._clients.get(client_id)
        if not (cached and time.monotonic() < cached[0]):
            self._start(client_id)

    async def _build_client(self, client_id: str, cached) -> ClientLexicon | None:
        try:
            sheet = await asyncio.wait_for(self._erp().get(f"/api/clients/{client_id}"), 4)
        except Exception as e:
            print(f"[lexicon] client sheet {client_id} unavailable ({type(e).__name__}); global lexicon only", flush=True)
            return cached[1] if cached else None
        mine = [r for r in await self.learned() if r.scope == client_id]
        lex = build_client(sheet, await self.catalogue(), mine)
        self._clients[client_id] = (time.monotonic() + cfg.CLIENT_TTL_S, lex)
        return lex

    async def indexes(self, client_id: str | None = None, wait: float | None = None) -> Indexes | None:
        """The indexes for this turn, or None when the catalogue is not available (no ERP): the caller skips the resolver."""
        cat = await self.catalogue()
        if cat is None:
            return None
        rows = [r for r in await self.learned() if r.scope == "global"]
        sig = hash(tuple((r.row_id, r.count) for r in rows))
        if sig != self._global_learned[0]:
            self._global_learned = (sig, Index([Entry(r.heard, r.etype, r.eid, r.label, "learned", "global", r.confidence, r.row_id) for r in rows]))
        lex = None
        if client_id:
            try:
                lex = await (asyncio.wait_for(self.client(client_id), wait) if wait else self.client(client_id))
            except Exception:  # too slow / ERP down: the global lexicon alone
                lex = None
        return Indexes([cat.index, self._global_learned[1], *([lex.index] if lex else [])], lex.usual if lex else {}, client_id if lex else None)

    async def client_terms(self, client_id: str | None) -> list[str]:
        """STT terms of a known caller, or [] (never raises, never waits long: a turn must not start late)."""
        if not client_id:
            return []
        try:
            lex = await asyncio.wait_for(self.client(client_id), cfg.HINT_CLIENT_WAIT_S)
        except Exception:  # includes the wait timeout
            return []
        return lex.terms if lex else []

    def invalidate(self) -> None:
        """Drop every cache (a learn / forget / reset): the next read goes to the ERP."""
        self._learned.drop()
        self._clients.clear()
        self._global_learned = (-1, Index())

    # ── writes (the ERP carries the actor: `erp` is the caller's client, e.g. ctx.erp) ──

    async def learn(self, erp: ErpClient, client_id: str, heard: str, etype: str, eid: str | None, label: str, source: str) -> dict:
        """Record "heard → entity" for this client. Call only after lexicon/guard.py accepted the evidence.
        Returns {id, scope, count, promoted}."""
        cat = await self.catalogue()
        if cat:  # trust the ERP's ids and names, not the model's
            if client_id not in cat.clients:
                raise L.LearnRefused(f"Client inconnu : {client_id}")
            known = {"client": cat.clients, "product": cat.products}.get(etype)
            if known is not None:
                if not eid or eid not in known:
                    raise L.LearnRefused(f"Identifiant inconnu pour {etype} : {eid}")
                label = known[eid]["name"] if etype == "client" else short_name(known[eid]["name"])
        heard = L.validate(heard, etype, eid, label)
        norm = L.squash_form(heard)
        if cat:  # the words already mean something else in the catalogue: a lesson would poison it
            for e in cat.index.exact_hits(norm):
                if e.entity != (etype, eid or label) and e.source != "jargon":
                    raise L.LearnRefused(f"« {heard} » désigne déjà « {e.label} » dans le catalogue : je ne l'apprends pas comme « {label} ».")
        today = await self.today()
        scope = "global" if etype == "client" else client_id  # a caller says their own name before being identified
        rows = await self._fresh_learned()
        pair = (norm, etype, eid)
        current = next((r for r in rows if r.scope == scope and r.pair == pair), None)
        new = L.Learned(heard, etype, eid, label, scope, 1, today, today, source, [client_id])
        merged = L.merge(current, new, today)
        if current and current.row_id:
            await erp.patch(f"/api/context/{current.row_id}", _patch(L.encode(merged)))
            merged.row_id = current.row_id
        else:
            merged.row_id = (await erp.post("/api/context", L.encode(merged)))["id"]
            rows = [*rows, merged]
        promoted = None
        for p in L.promotions([r if r.row_id != merged.row_id else merged for r in rows], today):
            promoted = (await erp.post("/api/context", L.encode(p)))["id"]
        self.invalidate()
        return {"id": merged.row_id, "scope": scope, "count": merged.count, "confidence": round(merged.confidence, 2), "promotedToGlobal": bool(promoted)}

    async def forget(self, erp: ErpClient, row_id: str) -> dict:
        row = next((r for r in await self._fresh_learned() if r.row_id == row_id), None)
        if row is None:
            raise LookupError(f"Aucune entrée de vocabulaire {row_id}")
        await erp.delete(f"/api/context/{row_id}")
        self.invalidate()
        return {"id": row_id, "forgot": row.heard, "scope": row.scope}

    async def forget_heard(self, erp: ErpClient, heard: str, client_id: str | None = None) -> list[dict]:
        """Forget every entry for this heard form (the client's own, and the global ones when no client is given)."""
        norm = L.squash_form(heard)
        rows = [r for r in await self._fresh_learned() if r.norm == norm and (client_id is None or r.scope in (client_id, "global"))]
        return [await self.forget(erp, r.row_id) for r in rows if r.row_id]

    async def prune(self, erp: ErpClient) -> list[str]:
        """Delete the entries never reused for too long (learned.expired). Returns the deleted row ids."""
        today = await self.today()
        gone = []
        for r in await self._fresh_learned():
            if r.row_id and L.expired(r, today):
                await erp.delete(f"/api/context/{r.row_id}")
                gone.append(r.row_id)
        self.invalidate()
        return gone

    async def _fresh_learned(self) -> list[L.Learned]:
        self._learned.drop()
        return await self.learned(include_expired=True)


def _patch(row: dict) -> dict:
    return {k: row[k] for k in ("title", "body", "tags")}


store = LexiconStore()

__all__ = ["ErpError", "Indexes", "LexiconStore", "store"]
