"""Provider-agnostic LLM abstraction core types.

Business logic depends only on :class:`BaseProvider` plus the small value objects
``Usage`` and ``CompletionResult`` -- never on a concrete backend. This is what
makes providers swappable without changing orchestration or agent logic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar, Dict, List, Optional


@dataclass(frozen=True)
class Usage:
    """Token accounting for a single completion call."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def __post_init__(self) -> None:
        if self.total_tokens == 0 and (self.prompt_tokens or self.completion_tokens):
            object.__setattr__(self, "total_tokens", self.prompt_tokens + self.completion_tokens)


@dataclass(frozen=True)
class CompletionResult:
    """Result of a provider completion call.

    The ``metadata`` bag carries provider-specific extras (e.g. raw id, finish
    reason) without polluting the stable surface.
    """

    content: str
    usage: Usage = field(default_factory=Usage)
    model: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class BaseProvider(ABC):
    """Abstract interface every LLM backend must implement.

    Subclasses declare their stable ``type`` identifier (e.g. ``openrouter``,
    ``huggingface``, ``custom``) which the :class:`ProviderRegistry` keys adapters
    by. A provider is constructed from a resolved configuration dict (already
    merged from the persisted ``Provider.auth_config`` plus env overrides), so
    adapter classes stay pure and free of persistence concerns.
    """

    type: ClassVar[str] = ""
    capabilities: ClassVar[Dict[str, bool]] = {}

    @classmethod
    def supports(cls, capability: str) -> bool:
        return bool(cls.capabilities.get(capability))

    @abstractmethod
    async def complete(
        self,
        messages: List[Dict[str, str]],
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> CompletionResult:
        """Run a chat completion and return content plus token usage."""

    async def close(self) -> None:
        """Release any underlying client resources. No-op by default."""


class ResolvedProviderConfig:
    """Small base that shares resolver/constructor plumbing across adapters.

    Adapters are built from a resolved ``config`` dict containing the merged
    provider configuration (auth keys, base_url, defaults, etc.).
    """

    def __init__(self, config: Dict[str, Any]) -> None:
        self.config: Dict[str, Any] = config or {}

    def _require(self, key: str) -> str:
        value = self.config.get(key)
        if not value:
            from ..errors import ProviderError

            raise ProviderError(f"Provider '{self.type}' requires '{key}'")
        return value