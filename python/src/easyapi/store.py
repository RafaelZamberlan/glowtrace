"""Execution storage.

``SQLiteStore`` writes on a dedicated thread (never blocks the event loop),
compresses payloads, and enforces retention (max count + max age).
``MemoryStore`` is for tests and ephemeral use.
"""
from __future__ import annotations

import json
import os
import queue
import sqlite3
import threading
import time
import zlib
from collections import OrderedDict
from typing import Optional

_SUMMARY_KEYS = (
    "id",
    "trace_id",
    "started_at",
    "method",
    "path",
    "route_id",
    "status",
    "duration_ms",
    "error",
    "frame_count",
)


def summary_of(ex: dict) -> dict:
    return {k: ex.get(k) for k in _SUMMARY_KEYS}


class Store:
    def put(self, execution: dict) -> None:
        raise NotImplementedError

    def list(self, route_id: Optional[str] = None, limit: int = 100, status: Optional[str] = None) -> list[dict]:
        raise NotImplementedError

    def get(self, ex_id: str) -> Optional[dict]:
        raise NotImplementedError

    def clear(self) -> int:
        raise NotImplementedError

    def close(self) -> None:
        pass

    def flush(self, timeout: float = 2.0) -> None:
        pass


def _match(s: dict, route_id: Optional[str], status: Optional[str]) -> bool:
    if route_id and s.get("route_id") != route_id:
        return False
    if status == "error" and not (s.get("error") or (s.get("status") or 0) >= 500):
        return False
    if status == "ok" and (s.get("error") or (s.get("status") or 0) >= 400):
        return False
    return True


class MemoryStore(Store):
    def __init__(self, max_executions: int = 500) -> None:
        self.max = max_executions
        self._data: "OrderedDict[str, dict]" = OrderedDict()
        self._lock = threading.Lock()

    def put(self, execution: dict) -> None:
        with self._lock:
            self._data[execution["id"]] = execution
            while len(self._data) > self.max:
                self._data.popitem(last=False)

    def list(self, route_id=None, limit=100, status=None):
        with self._lock:
            items = list(self._data.values())
        out = [summary_of(e) for e in reversed(items) if _match(e, route_id, status)]
        return out[:limit]

    def get(self, ex_id):
        with self._lock:
            return self._data.get(ex_id)

    def clear(self):
        with self._lock:
            n = len(self._data)
            self._data.clear()
            return n


class SQLiteStore(Store):
    def __init__(self, path: str, max_executions: int = 500, max_age_s: Optional[float] = 7 * 24 * 3600) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        self.path = path
        self.max = max_executions
        self.max_age = max_age_s
        self._q: "queue.Queue[Optional[dict]]" = queue.Queue(maxsize=1000)
        self._read_lock = threading.Lock()
        self._read = sqlite3.connect(path, check_same_thread=False)
        self._init(self._read)
        self._writer = threading.Thread(target=self._run, name="easyapi-store", daemon=True)
        self._writer.start()
        self.dropped = 0

    @staticmethod
    def _init(conn: sqlite3.Connection) -> None:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS executions (
                id TEXT PRIMARY KEY,
                started_at REAL,
                route_id TEXT,
                status INTEGER,
                is_error INTEGER,
                summary TEXT,
                data BLOB
            )"""
        )
        conn.execute("CREATE INDEX IF NOT EXISTS ix_ex_started ON executions(started_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS ix_ex_route ON executions(route_id, started_at)")
        conn.commit()

    def put(self, execution: dict) -> None:
        try:
            self._q.put_nowait(execution)
        except queue.Full:
            self.dropped += 1

    def _run(self) -> None:
        conn = sqlite3.connect(self.path)
        self._init(conn)
        n = 0
        while True:
            item = self._q.get()
            if item is None:
                self._q.task_done()
                break
            try:
                s = summary_of(item)
                is_err = 1 if (item.get("error") or (item.get("status") or 0) >= 500) else 0
                blob = zlib.compress(json.dumps(item, default=str).encode("utf-8"), 6)
                conn.execute(
                    "INSERT OR REPLACE INTO executions VALUES (?,?,?,?,?,?,?)",
                    (item["id"], item.get("started_at"), item.get("route_id"), item.get("status"), is_err, json.dumps(s, default=str), blob),
                )
                n += 1
                if n % 20 == 0:
                    self._retention(conn)
                conn.commit()
            except Exception:
                pass
            finally:
                self._q.task_done()
        conn.close()

    def _retention(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            "DELETE FROM executions WHERE id NOT IN (SELECT id FROM executions ORDER BY started_at DESC LIMIT ?)",
            (self.max,),
        )
        if self.max_age:
            conn.execute("DELETE FROM executions WHERE started_at < ?", (time.time() - self.max_age,))

    def flush(self, timeout: float = 2.0) -> None:
        end = time.time() + timeout
        while self._q.unfinished_tasks and time.time() < end:
            time.sleep(0.01)

    def list(self, route_id=None, limit=100, status=None):
        sql = "SELECT summary FROM executions"
        cond, args = [], []
        if route_id:
            cond.append("route_id = ?")
            args.append(route_id)
        if status == "error":
            cond.append("is_error = 1")
        elif status == "ok":
            cond.append("is_error = 0 AND status < 400")
        if cond:
            sql += " WHERE " + " AND ".join(cond)
        sql += " ORDER BY started_at DESC LIMIT ?"
        args.append(int(limit))
        with self._read_lock:
            rows = self._read.execute(sql, args).fetchall()
        return [json.loads(r[0]) for r in rows]

    def get(self, ex_id):
        with self._read_lock:
            row = self._read.execute("SELECT data FROM executions WHERE id = ?", (ex_id,)).fetchone()
        if not row:
            return None
        return json.loads(zlib.decompress(row[0]).decode("utf-8"))

    def clear(self):
        self.flush()
        with self._read_lock:
            cur = self._read.execute("DELETE FROM executions")
            self._read.commit()
            return cur.rowcount

    def close(self) -> None:
        self._q.put(None)
        self._writer.join(timeout=2)
        with self._read_lock:
            self._read.close()


_stores: dict[str, tuple[SQLiteStore, int]] = {}
_stores_lock = threading.Lock()


def acquire_sqlite_store(path: str, max_executions: int = 500, max_age_s: Optional[float] = None) -> SQLiteStore:
    """One writer thread / connection per database file, shared by all instances."""
    key = os.path.normcase(os.path.abspath(path))
    with _stores_lock:
        hit = _stores.get(key)
        if hit is not None:
            _stores[key] = (hit[0], hit[1] + 1)
            return hit[0]
        st = SQLiteStore(path, max_executions, max_age_s)
        _stores[key] = (st, 1)
        return st


def release_store(store: Store) -> None:
    if not isinstance(store, SQLiteStore):
        store.close()
        return
    key = os.path.normcase(os.path.abspath(store.path))
    with _stores_lock:
        hit = _stores.get(key)
        if hit is None or hit[0] is not store:
            store.close()
            return
        if hit[1] <= 1:
            _stores.pop(key, None)
            store.close()
        else:
            _stores[key] = (store, hit[1] - 1)
