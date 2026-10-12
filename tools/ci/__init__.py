"""Unified CI / SDLC pipeline for the platform (task items (a)+(b)).

The pipeline runs every backend module's test suite, then drives the Standard
SDLC workflow (ADR-016) with contract verification and independent quality
gates wired to the ``quality-gates`` service.

Public surface:
* :class:`tools.ci.pipeline.CIPipeline` — run the whole thing.
* :mod:`tools.ci.sdlc` — the SDLC phase engine (fix-loop bound, candidate
  invalidation, contract verification).
* :mod:`tools.ci.runner` — per-module pytest suite runner.
* :class:`tools.ci.pipeline.QualityGateApiClient` — HTTP client for the
  quality-gates service.
"""

from .pipeline import CIPipeline, PipelineReport, QualityGateApiClient
from .runner import (
    BACKEND_MODULES,
    SuiteResult,
    run_all_backend_suites,
    run_pytest_suite,
)
from .sdlc import (
    GateVerdict,
    SDLCError,
    SDLCPhase,
    SDLCWorkflow,
    standard_sdlc_phases,
)

__all__ = [
    "BACKEND_MODULES",
    "CIPipeline",
    "GateVerdict",
    "PipelineReport",
    "QualityGateApiClient",
    "SDLCError",
    "SDLCPhase",
    "SDLCWorkflow",
    "SuiteResult",
    "run_all_backend_suites",
    "run_pytest_suite",
    "standard_sdlc_phases",
]