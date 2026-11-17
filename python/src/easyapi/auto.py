"""Zero-code instrumentation: install EasyAPI on every Starlette/FastAPI app.

The first time an app is called (lifespan or first request) EasyAPI is attached
to it. Configure with the usual EASYAPI_*
environment variables.

Entry points:
    python -m easyapi run uvicorn main:app        # wraps any command (sitecustomize)
    pytest -p easyapi.pytest_plugin                # instrument apps built by a test suite
    import easyapi.auto; easyapi.auto.install()    # programmatic
"""
from __future__ import annotations

import logging
import weakref
from typing import Any

log = logging.getLogger("easyapi")

_installed = False
_seen: "weakref.WeakSet[Any]" = weakref.WeakSet()
instances: list = []  # EasyAPI objects created automatically (for stats)
_original: dict = {}


def uninstall() -> None:
    global _installed
    if not _installed:
        return
    from starlette.applications import Starlette

    Starlette.__call__ = _original.pop("call")  # type: ignore[method-assign]
    _installed = False


def install(**kwargs: Any) -> bool:
    """Patch Starlette so every app gets EasyAPI. Returns False if Starlette is missing."""
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
            if getattr(self, "_easyapi_internal", False):
                pass  # EasyAPI's own /_easyapi app
            elif getattr(getattr(self, "state", None), "easyapi", None) is None:
                try:
                    from .core import EasyAPI

                    instances.append(EasyAPI(self, **kwargs))
                except Exception:  # never break the host app
                    log.exception("easyapi.auto: could not instrument %r", self)
        await original_call(self, scope, receive, send)

    Starlette.__call__ = __call__  # type: ignore[method-assign]
    _original["call"] = original_call
    _installed = True
    return True
