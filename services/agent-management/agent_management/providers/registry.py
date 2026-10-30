"""Provider registry: maps stable ``type`` identifiers to adapter classes.

Business logic never imports a concrete adapter class directly -- it asks the
registry to build a provider from a persisted ``Provider`` record's ``type`` plus a
resolved config dict. This keeps adding a new backend down to one new class plus
one ``register`` call(and preserves provider independence at every call site.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Type

from .adapters import CustomProvider, HuggingFaceProvider, MockProvider, OpenRouterProvider
from .base import BaseProvider
from ..errors import ProviderNotFoundError


class ProviderRegistry:
    """Registry of adapter classes keyed by their ``type`` ClassVar."""

    def __init__(self) -> None:
        self._adapters: Dict[str, Type[BaseProvider]] = {}

    def register(self, adapter: Type[BaseProvider]) -> None:
        type_id = adapter.type
        if not type_id:
            raise ValueError(f"Adapter {adapter.__name__} has empty 'type'")
        self._adapters[type_id] = adapter
        return adapter  # allow @registry.register decorator usage

    def unregister(self, type_id: str) -> None:
        self._adapters.pop(type_id, None)

    def get(self, type_id: str) -> Type[BaseProvider]:
        adapter = self._adapters.get(type_id)
        if adapter is None:
            known = ", ".join(sorted(self._adapters)) or "none"
            raise ProviderNotFoundError(
                f"No provider adapter registered for type '{type_id}'. Known: {known}"
            )
        return adapter

    def types(self) -> list[str]:
        return sorted(self._adapters)

    def build(
        self, type_id: str, config: Optional[Dict[str, Any]] = None
    ) -> BaseProvider:
        adapter = self.get(type_id)
        return adapter(config or {})

    def register_defaults(self) -> "ProviderRegistry":
        """Register the built-in adapters."""
        self.register(OpenRouterProvider)
        self.register(HuggingFaceProvider)
        self.register(CustomProvider)
        self.register(MockProvider)
        return self


# Module-level default registry shared by the service layer and callers.
DEFAULT_REGISTRY = ProviderRegistry().register_defaults()


def get_registry() -> ProviderRegistry:
    """Return the process-wide default registry (tests may build their own)."""
    return DEFAULT_REGISTRY