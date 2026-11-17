"""Glowtrace - see your API as a flow and watch every request run through it."""
from __future__ import annotations

__version__ = "0.2.0"

from .core import Glowtrace  # noqa: E402
from .runtime.capture import CaptureConfig  # noqa: E402
from .runtime.recorder import Limits, current as _current  # noqa: E402


def is_replay() -> bool:
    """True while handling a request re-sent by Glowtrace's replay (skip e-mails, charges...)."""
    rec = _current.get()
    return bool(rec is not None and rec.replay_of)


__all__ = ["Glowtrace", "CaptureConfig", "Limits", "is_replay", "__version__"]
