"""Loaded automatically by `python -m easyapi run ...` (placed first on PYTHONPATH)."""
import os
import sys

if os.environ.get("EASYAPI_AUTO") == "1":
    try:
        import easyapi.auto

        easyapi.auto.install()
    except Exception as exc:  # pragma: no cover
        sys.stderr.write(f"easyapi: auto-instrumentation disabled ({exc})\n")

# chain to a project's own sitecustomize, if any
_here = os.path.dirname(os.path.abspath(__file__))
_rest = [p for p in sys.path if os.path.abspath(p or ".") != _here]
try:
    import importlib.machinery
    import importlib.util

    _spec = importlib.machinery.PathFinder.find_spec("sitecustomize", _rest)
    if _spec is not None and _spec.origin and os.path.dirname(os.path.abspath(_spec.origin)) != _here:
        _mod = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)  # type: ignore[union-attr]
except Exception:
    pass
