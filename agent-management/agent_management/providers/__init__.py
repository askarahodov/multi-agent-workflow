"""LLM provider abstraction layer.

Exposes the provider-agnostic interface (:class:`BaseProvider`), the value objects
``Usage`` and ``CompletionResult``, the pluggable adapters (OpenRouter, HuggingFace,
custom, mock), and the :class:`ProviderRegistry` used to build providers by type so the
rest of the subsystem stays backend-agnostic.
"""

from __future__ import annotations

from .base import BaseProvider, CompletionResult, Usage
from .registry import DEFAULT_REGISTRY, ProviderRegistry, get_registry
from .adapters import (
    CustomProvider,
    HuggingFaceProvider,
    MockProvider,
    OpenRouterProvider,
)

__all__ = [
    "BaseProvider",
    "CompletionResult",
    "Usage",
    "ProviderRegistry",
    "DEFAULT_REGISTRY",
    "get_registry",
    "CustomProvider",
    "HuggingFaceProvider",
    "MockProvider",
    "OpenRouterProvider",
]