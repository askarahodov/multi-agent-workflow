"""Agent management subsystem and LLM provider abstraction layer.

Provides:
- Agent definitions (templates) and runtime agent instances with lifecycle management.
- A provider-agnostic LLM abstraction (BaseProvider) with pluggable adapters
  (OpenRouter, HuggingFace, custom), a factory wrapping because registry.
- Model profiles bound to providers, token usage tracking, and tool policy
  enforcement (filesystem, Git, shell, network permissions).
"""

from __future__ import annotations

__version__ = "0.1.0"