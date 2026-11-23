"""
Session memory: a voice conversation survives a reconnect, an uvicorn hot reload and a container recreate.

    SQLite file  $AI_STATE_DIR/sessions.db   (default <repo>/.state, git-ignored; the compose volume `ai-state` mounts /state)
    one row per sessionId:  id · updated · meta (JSON: every JSON-able field of Conversation) · history (JSON: ChatMessage list)

  - WRITE-THROUGH after each committed turn (and after a compaction): a crash loses at most the turn in flight, which was
    never committed to the history anyway. The write is a few ms (WAL, one small row), done outside the audio path.
  - LOAD on reconnect with the same sessionId (`restore`), unless the row is older than SESSION_TTL_HOURS (default 12 h).
  - CAP: SESSION_MAX (default 200) sessions, oldest `updated` evicted first; expired rows are purged at most once a minute.
  - `reset` deletes the row (`forget`).
  - NEVER breaks a session: a missing / unwritable directory, a locked or corrupted database → one log line, then the service
    runs memory-only exactly as before. A database file that is not a database is moved aside (`*.corrupt-<time>`) and recreated.

Thinking blocks (anthropic.py `_thinking_by_call`) are NOT persisted: they live in memory only and the Messages API only requires
them for the assistant turn of the tool loop that is currently running. Only COMPLETE turns are ever stored, so a reloaded history
contains previous turns' tool rounds without their thinking, which the API accepts (it ignores/strips thinking of earlier turns).
Cost: the prompt-cache prefix of the conversation differs once after a reload (one cache write), nothing else.

Compaction (services/compaction.py) is scheduled here, after the turn is committed, in a background task.
"""

import asyncio
import dataclasses
import json
import os
import sqlite3
import threading
import time
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Any

from app.agent.sanitize import sanitize_history
from app.config import REPO_ROOT, env
from app.schemas import ChatMessage

from . import compaction

DB_NAME = "sessions.db"
SCHEMA = 1
PURGE_EVERY_S = 60
HARD_CAP_MESSAGES = 160  # last resort if compaction cannot shrink a pathological history (e.g. one huge turn)


def env_number(name: str, default: float) -> float:
    try:
        return float(env(name) or default)
    except ValueError:
        return default


@dataclasses.dataclass(frozen=True)
class MemorySettings:
    directory: Path
    ttl_s: float  # SESSION_TTL_HOURS
    max_sessions: int  # SESSION_MAX
    policy: compaction.Policy  # COMPACT_KEEP_TURNS / COMPACT_TRIGGER_TURNS / COMPACT_MAX_CHARS
    llm_refine: bool  # COMPACT_LLM=1 (default off): one extra model call per compaction, in the background

    @classmethod
    def from_env(cls) -> "MemorySettings":
        directory = Path(env("AI_STATE_DIR", ".state")).expanduser()
        return cls(
            directory=directory if directory.is_absolute() else REPO_ROOT / directory,
            ttl_s=env_number("SESSION_TTL_HOURS", 12) * 3600,
            max_sessions=int(env_number("SESSION_MAX", 200)),
            policy=compaction.Policy(
                keep_turns=int(env_number("COMPACT_KEEP_TURNS", 6)),
                trigger_turns=int(env_number("COMPACT_TRIGGER_TURNS", 12)),
                max_chars=int(env_number("COMPACT_MAX_CHARS", 48_000)),
            ),
            llm_refine=env("COMPACT_LLM", "0").lower() in ("1", "true", "yes", "on"),
        )


class SessionStore:
    """SQLite persistence of conversations. Every method is safe to call when the store is unusable: it just does nothing."""

    def __init__(self, cfg: MemorySettings, clock: Callable[[], float] = time.time):
        self.cfg, self.clock = cfg, clock
        self.db: sqlite3.Connection | None = None
        self.enabled = True
        self.lock = threading.Lock()
        self.purged_at = 0.0

    # ── connection ──

    def disable(self, why: str) -> None:
        if self.enabled:
            print(f"[memory] session persistence OFF, memory only: {why}", flush=True)
        self.enabled, self.db = False, None

    def connect(self) -> sqlite3.Connection | None:
        if not self.enabled:
            return None
        if self.db is None:
            path = self.cfg.directory / DB_NAME
            try:
                self.cfg.directory.mkdir(parents=True, exist_ok=True)
                self.db = self.open_db(path)
            except (OSError, sqlite3.Error) as e:
                self.disable(f"{path}: {type(e).__name__}: {e}")
        return self.db

    def open_db(self, path: Path) -> sqlite3.Connection:
        try:
            return self.init_db(path)
        except sqlite3.DatabaseError as e:  # "file is not a database", malformed image…: keep the evidence, start clean
            if "locked" in str(e) or "readonly" in str(e) or "unable to open" in str(e):
                raise
            aside = path.with_name(f"{DB_NAME}.corrupt-{int(self.clock())}")
            os.replace(path, aside)
            print(f"[memory] corrupted session database moved to {aside.name} ({e}); starting empty", flush=True)
            return self.init_db(path)

    def init_db(self, path: Path) -> sqlite3.Connection:
        db = sqlite3.connect(path, timeout=2.0, check_same_thread=False, isolation_level=None)
        try:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=NORMAL")
            db.execute("CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, updated REAL NOT NULL, meta TEXT NOT NULL, history TEXT NOT NULL)")
            db.execute("CREATE INDEX IF NOT EXISTS sessions_updated ON sessions(updated)")
            db.execute("SELECT count(*) FROM sessions").fetchone()  # a corrupted file fails here, not later in a turn
            db.execute(f"PRAGMA user_version={SCHEMA}")
        except BaseException:
            db.close()
            raise
        return db

    def run(self, work: Callable[[sqlite3.Connection], Any], default: Any = None) -> Any:
        """Run `work` on the connection; any database error disables nothing but is logged once and returns `default`."""
        with self.lock:
            db = self.connect()
            if db is None:
                return default
            try:
                return work(db)
            except (sqlite3.Error, OSError) as e:
                # a transient problem (locked) must not switch persistence off for good; a broken file is handled at the next open
                with suppress(sqlite3.Error):
                    db.close()
                self.db = None
                self.fail_once(e)
                return default

    failed = False

    def fail_once(self, e: Exception) -> None:
        if not self.failed:
            print(f"[memory] session database error, this operation is skipped: {type(e).__name__}: {e}", flush=True)
            self.failed = True

    # ── operations ──

    def save(self, sid: str, meta: dict, history: list[ChatMessage]) -> list[str]:
        """Write-through. Returns the ids evicted by the cap (the caller drops them from its in-memory registry)."""
        now = self.clock()
        row = (sid, now, json.dumps(meta, ensure_ascii=False), json.dumps([m.to_wire() for m in history], ensure_ascii=False, separators=(",", ":")))

        def work(db: sqlite3.Connection) -> list[str]:
            db.execute("INSERT INTO sessions(id, updated, meta, history) VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET updated=excluded.updated, meta=excluded.meta, history=excluded.history", row)
            gone = self.purge_expired(db, now)
            (count,) = db.execute("SELECT count(*) FROM sessions").fetchone()
            if count > self.cfg.max_sessions:
                ids = [r[0] for r in db.execute("SELECT id FROM sessions ORDER BY updated ASC LIMIT ?", (count - self.cfg.max_sessions,))]
                db.executemany("DELETE FROM sessions WHERE id=?", [(i,) for i in ids])
                gone += ids
            return gone

        return self.run(work, [])

    def purge_expired(self, db: sqlite3.Connection, now: float) -> list[str]:
        if now - self.purged_at < PURGE_EVERY_S:
            return []
        self.purged_at = now
        ids = [r[0] for r in db.execute("SELECT id FROM sessions WHERE updated < ?", (now - self.cfg.ttl_s,))]
        db.execute("DELETE FROM sessions WHERE updated < ?", (now - self.cfg.ttl_s,))
        return ids

    def load(self, sid: str) -> tuple[dict, list[ChatMessage]] | None:
        now = self.clock()

        def work(db: sqlite3.Connection):
            row = db.execute("SELECT updated, meta, history FROM sessions WHERE id=?", (sid,)).fetchone()
            if row is None:
                return None
            if row[0] < now - self.cfg.ttl_s:
                db.execute("DELETE FROM sessions WHERE id=?", (sid,))
                return None
            try:
                return json.loads(row[1]), [ChatMessage.model_validate(m) for m in json.loads(row[2])]
            except (ValueError, TypeError) as e:  # a row nobody can read: drop it, the caller starts a fresh conversation
                print(f"[memory] unreadable session {sid} dropped: {type(e).__name__}", flush=True)
                db.execute("DELETE FROM sessions WHERE id=?", (sid,))
                return None

        return self.run(work)

    def delete(self, sid: str) -> None:
        self.run(lambda db: db.execute("DELETE FROM sessions WHERE id=?", (sid,)))

    def count(self) -> int:
        return self.run(lambda db: db.execute("SELECT count(*) FROM sessions").fetchone()[0], 0)

    def close(self) -> None:
        with self.lock:
            if self.db is not None:
                self.db.close()
            self.db = None


_store: SessionStore | None = None


def get_store() -> SessionStore:
    global _store
    if _store is None:
        _store = SessionStore(MemorySettings.from_env())
    return _store


def set_store(store: SessionStore | None) -> None:
    """Tests (and nothing else) swap the store."""
    global _store
    if _store is not None and _store is not store:
        _store.close()
    _store = store


# ── Conversation glue (duck-typed: any dataclass with `id` and `history`, so other fields added later are persisted too) ──


def snapshot(conv) -> dict:
    """The JSON-able fields of a conversation (history aside): primitives and dataclasses such as the declared caller."""
    meta: dict = {}
    for f in dataclasses.fields(conv):
        if f.name in ("id", "history"):
            continue
        v = getattr(conv, f.name)
        if v is None or isinstance(v, (str, int, float, bool)):
            meta[f.name] = v
        elif isinstance(v, (dict, list)):
            try:
                json.dumps(v)
                meta[f.name] = v
            except (TypeError, ValueError):
                pass
        elif dataclasses.is_dataclass(v) and not isinstance(v, type):
            meta[f.name] = {"__dataclass__": dataclasses.asdict(v)}
    return meta


def restore(cls, sid: str):
    """A Conversation rebuilt from the store, or None (unknown, expired, unreadable, store unusable)."""
    if not sid:
        return None
    loaded = get_store().load(sid)
    if loaded is None:
        return None
    meta, history = loaded
    conv = cls(id=sid)
    known = {f.name for f in dataclasses.fields(conv)}
    for name, value in meta.items():
        if name not in known or name in ("id", "history"):
            continue
        if isinstance(value, dict) and "__dataclass__" in value:
            template = getattr(conv, name)
            try:
                value = type(template)(**value["__dataclass__"])
            except TypeError:
                continue
        setattr(conv, name, value)
    conv.history = history
    return conv


def persist(conv, registry: dict | None = None) -> None:
    """Write-through; conversations evicted by the cap are dropped from `registry` too (unless it is the one being saved)."""
    evicted = get_store().save(conv.id, snapshot(conv), conv.history)
    if registry is not None:
        for sid in evicted:
            if sid != conv.id:
                registry.pop(sid, None)


def forget(conv) -> None:
    get_store().delete(conv.id)


# ── committing a turn ──


def commit(conv, base: list[ChatMessage], working: list[ChatMessage], registry: dict | None = None) -> None:
    """The turn is over: `working` (= `base` + the turn's messages) becomes the history, and is stored.

    `base` is the history object the turn started from. If a compaction replaced `conv.history` meanwhile (it runs in the background),
    only the turn's own new messages are appended to the compacted history, so the compaction is not undone."""
    full = [*conv.history, *working[len(base) :]] if conv.history is not base else working
    history = sanitize_history(full)
    if len(history) > HARD_CAP_MESSAGES:
        history = sanitize_history(history[-HARD_CAP_MESSAGES:])  # re-sanitised: the cut may start mid-turn
    conv.history = history
    persist(conv, registry)


_tasks: set[asyncio.Task] = set()  # strong references: a bare create_task() may be garbage-collected before it finishes


def background(coro) -> asyncio.Task:
    task = asyncio.create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return task


async def compact_later(conv, llm=None, registry: dict | None = None, policy: compaction.Policy | None = None, refine: bool | None = None) -> bool:
    """After a committed turn: fold the old turns into a summary, if the history is long enough. Meant for `asyncio.create_task`:
    it never runs on the critical path of a turn, and never raises. The result is applied only if the history was not changed
    meanwhile (a newer turn rebases onto it in `commit`). Returns True when a compaction was applied."""
    cfg = get_store().cfg
    policy = policy or cfg.policy
    try:
        base = conv.history
        if not compaction.needs_compaction(base, policy):
            return False
        history, facts, folded = compaction.compact(base, conv.facts, policy)
        if not folded or conv.history is not base:
            return False
        conv.history, conv.facts = history, facts
        persist(conv, registry)
        print(f"[memory] {conv.id[:8]} compacted: {folded} messages folded, {len(history)} kept, summary {len(history[0].content)} chars", flush=True)
        if (cfg.llm_refine if refine is None else refine) and llm is not None and llm.provider != "mock":
            summary = history[0]
            better = await compaction.refine(llm, summary.content)
            if better and conv.history and conv.history[0] is summary:
                conv.history = [summary.model_copy(update={"content": better}), *conv.history[1:]]
                persist(conv, registry)
        return True
    except asyncio.CancelledError:
        raise
    except Exception as e:  # the summary is a nicety: a bug here must never reach the call
        print(f"[memory] compaction failed, history left as is: {type(e).__name__}: {e}", flush=True)
        return False
