"""Glowtrace entry point."""
from __future__ import annotations

import fnmatch
import logging
import os
import sys
import threading
import traceback
from typing import Any, Callable, Optional, Sequence, Union

from .integrations.fastapi import (
    GlowtraceMiddleware,
    FastAPIAdapter,
    build_execution,
    should_sample,
)
from .runtime.backends import Backend, acquire_backend, release_backend
from .runtime.capture import Capturer, CaptureConfig
from .runtime.recorder import Limits, Recorder
from .static.registry import Registry
from .store import MemoryStore, Store, acquire_sqlite_store, release_store

log = logging.getLogger("glowtrace")

_DEFAULT_IGNORE = (
    "/docs",
    "/docs/*",
    "/redoc",
    "/openapi.json",
    "/favicon.ico",
)

MODES = ("off", "graph", "trace")


def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    v = os.environ.get(name)
    return v if v not in (None, "") else default


# how much of each value is kept: env > CaptureConfig > defaults; clamped to sane bounds
_LIMITS = (
    # env var, CaptureConfig field, min, max
    ("GLOWTRACE_MAX_DEPTH", "max_depth", 1, 200),
    ("GLOWTRACE_MAX_ITEMS", "max_items", 1, 10_000),
    ("GLOWTRACE_MAX_VALUES", "budget", 10, 1_000_000),
    ("GLOWTRACE_MAX_STR", "max_str", 20, 1_000_000),
)


def capture_limits(cfg: CaptureConfig) -> CaptureConfig:
    import dataclasses

    changes = {}
    for env, field_name, lo, hi in _LIMITS:
        raw = _env(env)
        value = getattr(cfg, field_name)
        if raw is not None:
            try:
                value = int(raw)
            except ValueError:
                import warnings

                warnings.warn(f"{env}={raw!r} não é um número; usando {value}", stacklevel=3)
        changes[field_name] = max(lo, min(hi, int(value)))
    return dataclasses.replace(cfg, **changes)


class Glowtrace:
    """Plug Glowtrace into an ASGI app (FastAPI / Starlette).

    >>> app = FastAPI()
    >>> Glowtrace(app)            # map at /_glowtrace, executions recorded

    Modes: ``"graph"`` (map only, zero runtime cost), ``"trace"`` (map +
    per-request recording), ``"off"``. Every option can also be set via
    environment variables (``GLOWTRACE_MODE``, ``GLOWTRACE_SAMPLE``,
    ``GLOWTRACE_TOKEN``, ``GLOWTRACE_DB``, ``GLOWTRACE_ROOTS``...).
    """

    def __init__(
        self,
        app: Any,
        *,
        mode: Optional[str] = None,
        prefix: str = "/_glowtrace",
        roots: Optional[Sequence[str]] = None,
        exclude: Optional[Sequence[str]] = None,
        sample_rate: Optional[float] = None,
        trace_paths: Optional[Sequence[str]] = None,
        ignore_paths: Sequence[str] = _DEFAULT_IGNORE,
        store: Union[str, Store, None] = None,
        db_path: Optional[str] = None,
        max_executions: int = 500,
        retention_seconds: Optional[float] = 7 * 24 * 3600,
        token: Optional[str] = None,
        allow_remote: Optional[bool] = None,
        auth: Optional[Callable[[dict], bool]] = None,
        capture: Optional[CaptureConfig] = None,
        limits: Optional[Limits] = None,
        max_body: int = 32_768,
        expose_header: bool = True,
        replay: Optional[bool] = None,
        backend: Optional[str] = None,
        title: Optional[str] = None,
    ) -> None:
        existing = getattr(getattr(app, "state", None), "glowtrace", None)
        if existing is not None:
            raise RuntimeError("Glowtrace already installed on this app")

        if _env("GLOWTRACE_ENABLED") in ("0", "false", "False", "no"):
            mode = "off"
        self.mode = (_env("GLOWTRACE_MODE", mode) or "trace").lower()
        if self.mode not in MODES:
            raise ValueError(f"Glowtrace mode must be one of {MODES}, got {self.mode!r}")
        self.app = app
        self.prefix = "/" + prefix.strip("/")
        env_roots = _env("GLOWTRACE_ROOTS")
        self.roots = list(roots) if roots else (env_roots.split(os.pathsep) if env_roots else [os.getcwd()])
        self.sample_rate = float(_env("GLOWTRACE_SAMPLE", str(sample_rate if sample_rate is not None else 1.0)))
        self.trace_paths = list(trace_paths) if trace_paths else None
        self.ignore_paths = list(ignore_paths)
        self.token = _env("GLOWTRACE_TOKEN", token)
        ar = _env("GLOWTRACE_ALLOW_REMOTE")
        self.allow_remote = (ar in ("1", "true", "True")) if ar is not None else bool(allow_remote)
        self.auth = auth
        self.max_body = max_body
        eh = _env("GLOWTRACE_EXPOSE_HEADER")
        self.expose_header = (eh not in ("0", "false", "False")) if eh is not None else expose_header
        self.limits = limits or Limits()
        self.title = title or getattr(app, "title", None) or "API"
        self._lock = threading.Lock()
        self.observed_edges: dict[tuple[str, str], int] = {}
        # Replay re-sends recorded requests into the app: OFF unless explicitly enabled
        # (GLOWTRACE_REPLAY=1 or replay=True). Meant for development environments only.
        rp = _env("GLOWTRACE_REPLAY")
        self.replay_enabled = (rp in ("1", "true", "True", "yes")) if rp is not None else bool(replay)
        self._pending_replays: dict[str, dict] = {}
        self.internal_errors = 0

        self.registry = Registry(self.roots, list(exclude) if exclude else None)
        self.capturer = Capturer(capture_limits(capture or CaptureConfig()))
        self.adapter = FastAPIAdapter(app, self)

        # storage
        if isinstance(store, Store):
            self.store: Store = store
        else:
            kind = (_env("GLOWTRACE_STORE", store) or "sqlite").lower()
            if kind == "memory":
                self.store = MemoryStore(max_executions)
            else:
                path = _env("GLOWTRACE_DB", db_path) or os.path.join(os.getcwd(), ".glowtrace", "glowtrace.db")
                self.store = acquire_sqlite_store(path, max_executions, retention_seconds)

        # runtime backend
        self.backend: Optional[Backend] = None
        if self.mode == "trace":
            if not hasattr(sys, "monitoring") and sys.gettrace() is not None:
                log.warning("glowtrace: a tracer/debugger is already active; sys.settrace backend will replace it")
            self.backend = acquire_backend(self.registry, _env("GLOWTRACE_BACKEND", backend))

        from .server import build_server

        self.server = build_server(self)
        self._install_middleware()
        try:
            app.state.glowtrace = self
        except Exception:
            pass
        log.info(
            "glowtrace: mode=%s backend=%s ui=%s roots=%s",
            self.mode,
            self.backend.name if self.backend else None,
            self.prefix,
            self.roots,
        )

    # ------------------------------------------------------------------
    def _install_middleware(self) -> None:
        if self.mode == "off":
            return
        app = self.app
        original = app.build_middleware_stack
        core = self

        def build_middleware_stack():
            return GlowtraceMiddleware(original(), core)

        app.build_middleware_stack = build_middleware_stack  # type: ignore[method-assign]
        if getattr(app, "middleware_stack", None) is not None:
            # Old Starlette (< 0.24) builds the stack eagerly and never rebuilds a
            # None stack; an already-started new Starlette app is in the same spot.
            # Rebuild right away so the wrapper is in place in both cases.
            app.middleware_stack = app.build_middleware_stack()

    def should_trace(self, scope: dict) -> bool:
        if self.mode != "trace":
            return False
        if scope.get("method") == "OPTIONS":
            return False
        headers = scope.get("headers") or []
        forced = None
        for k, v in headers:
            if k == b"x-glowtrace-trace":
                forced = v.strip() not in (b"0", b"false")
                break
        if forced is False:
            return False
        path = scope.get("path", "")
        if any(fnmatch.fnmatchcase(path, p) for p in self.ignore_paths):
            return False
        if self.trace_paths is not None and not any(fnmatch.fnmatchcase(path, p) for p in self.trace_paths):
            return False
        if forced:
            return True
        return should_sample(self.sample_rate)

    def finish(self, rec: Recorder, scope, hdict, trace_id, req_parts, req_state, resp, error) -> None:
        ex = build_execution(self, rec, scope, hdict, trace_id, req_parts, req_state, resp, error)
        by_id = {f["id"]: f for f in ex["frames"]}
        with self._lock:
            for f in ex["frames"]:
                p = by_id.get(f.get("parent"))
                if p is not None:
                    key = (p["fn"], f["fn"])
                    self.observed_edges[key] = self.observed_edges.get(key, 0) + 1
        self.store.put(ex)

    def register_replay(self, replay_of: Optional[str], edits: list[str]) -> str:
        """Reserve an execution id for a replay started by our own server."""
        import uuid

        rid = uuid.uuid4().hex[:16]
        with self._lock:
            self._pending_replays[rid] = {"id": rid, "replay_of": replay_of, "edits": edits[:50]}
        return rid

    def claim_replay(self, scope: dict) -> Optional[dict]:
        """The replay a request belongs to - only if our server registered it (headers alone are not trusted)."""
        if not self._pending_replays:
            return None
        for k, v in scope.get("headers") or []:
            if k == b"x-glowtrace-replay-id":
                with self._lock:
                    return self._pending_replays.pop(v.decode("latin-1"), None)
        return None

    def log_internal_error(self) -> None:
        self.internal_errors += 1
        if self.internal_errors <= 5:
            log.error("glowtrace internal error (request unaffected):\n%s", traceback.format_exc())

    # ------------------------------------------------------------------
    def close(self) -> None:
        if self.backend is not None:
            release_backend(self.registry)
            self.backend = None
        release_store(self.store)
