"""Zero-code instrumentation: install Glowtrace on every Starlette/FastAPI app.

The first time an app is called (lifespan or first request) Glowtrace is attached
to it. Configure with the usual GLOWTRACE_*
environment variables.

Entry points:
    python -m glowtrace run uvicorn main:app        # wraps any command (sitecustomize)
    pytest -p glowtrace.pytest_plugin                # instrument apps built by a test suite
    import glowtrace.auto; glowtrace.auto.install()    # programmatic
"""
from __future__ import annotations

import logging
import weakref
from typing import Any

log = logging.getLogger("glowtrace")

_installed = False
_seen: "weakref.WeakSet[Any]" = weakref.WeakSet()
instances: list = []  # Glowtrace objects created automatically (for stats)
_original: dict = {}


def uninstall() -> None:
    global _installed
    if not _installed:
        return
    from starlette.applications import Starlette

    Starlette.__call__ = _original.pop("call")  # type: ignore[method-assign]
    _installed = False


def install(**kwargs: Any) -> bool:
    """Patch Starlette so every app gets Glowtrace. Returns False if Starlette is missing."""
    global _installed
    if _installed:
        return True
    try:
        from starlette.applications import Starlette
    except Exception:  # pragma: no cover - starlette not installed
        return False
    original_call = Starlette.__call__

    async def __call__(self, scope, receive, send):  # type: ignore[no-untyped-def]
        # FastAPI overrides build_middleware_stack but always reaches Starlette.__call__
        if self not in _seen:
            _seen.add(self)
            if getattr(self, "_glowtrace_internal", False):
                pass  # Glowtrace's own /_glowtrace app
            elif getattr(getattr(self, "state", None), "glowtrace", None) is None:
                try:
                    from .core import Glowtrace

                    instances.append(Glowtrace(self, **kwargs))
                except Exception:  # never break the host app
                    log.exception("glowtrace.auto: could not instrument %r", self)
        await original_call(self, scope, receive, send)

    Starlette.__call__ = __call__  # type: ignore[method-assign]
    _original["call"] = original_call
    _installed = True
    return True
