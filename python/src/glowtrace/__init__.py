"""Glowtrace - see your API as a flow and watch every request run through it."""
from __future__ import annotations

__version__ = "0.2.0"

from .core import Glowtrace  # noqa: E402
from .runtime.capture import CaptureConfig  # noqa: E402
from .runtime.recorder import Limits  # noqa: E402

__all__ = ["Glowtrace", "CaptureConfig", "Limits", "__version__"]
