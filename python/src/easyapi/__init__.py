"""EasyAPI - see your API as a flow and watch every request run through it."""
from __future__ import annotations

__version__ = "0.1.1"

from .core import EasyAPI  # noqa: E402
from .runtime.capture import CaptureConfig  # noqa: E402
from .runtime.recorder import Limits  # noqa: E402

__all__ = ["EasyAPI", "CaptureConfig", "Limits", "__version__"]
