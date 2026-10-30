"""Quality gates subsystem: automated Tester, Reviewer, Security, Release-Prep gates."""

from __future__ import annotations

__version__ = "0.1.0"

from .config import BUILTIN_GATES, Settings
from .pipeline import GatePipeline
from .gates.base import GATE_REGISTRY

__all__ = ["BUILTIN_GATES", "Settings", "GatePipeline", "GATE_REGISTRY", "__version__"]
