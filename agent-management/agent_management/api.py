"""FastAPI application for the agent-management subsystem.

Exposes REST endpoints for providers, model profiles, tool policies, agent
definitions, agent instances (incl. lifecycle transitions), token usage, and a
LLM completion endpoint that exercises the provider abstraction end to end. Errors
are rendered as RFC 9457 Problem Details documents.

The router is deliberately kept thin: all domain logic lives in the service layer
so business rules can be tested independently of HTTP.
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, FastAPI, Query, Request
from fastapi.responses import JSONResponse

from .errors import AgentManagementError
from .schemas import (
    AgentDefinitionCreate,
    AgentDefinitionListResponse,
    AgentDefinitionResponse,
    AgentDefinitionUpdate,
    AgentInstanceCreate,
    AgentInstanceListResponse,
    AgentInstanceResponse,
    CompleteRequest,
    CompleteResponse,
    LifecycleAction,
    ModelProfileCreate,
    ModelProfileListResponse,
    ModelProfileResponse,
    ModelProfileUpdate,
    ProviderCreate,
    ProviderListResponse,
    ProviderResponse,
    ProviderUpdate,
    ToolPolicyCreate,
    ToolPolicyListResponse,
    ToolPolicyResponse,
    ToolPolicyUpdate,
    UsageListResponse,
    UsageSummaryResponse,
)
from .services import AgentManagementService


async def problem_handler(_request: Request, exc: AgentManagementError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.to_problem(),
        headers={"Content-Type": "application/problem+json"},
    )


def _cursor_page(rows: List, total: int, limit: int, offset: int = 0) -> dict:
    """Render a list payload in the ADR-101 CursorPage-compatible envelope.

    Keeps the existing ``items``/``total`` fields (backward compatible) and
    adds ``next_cursor`` so the frontend (which consumes CursorPage) can page
    without a separate offset/limit transform on its side. ``next_cursor`` is
    ``None`` when the returned page is the last one.
    """
    if offset > 0 or limit < len(rows):
        page = rows[offset : offset + limit]
    else:
        page = rows
    next_cursor = None
    if page and (offset + len(page)) < total:
        last = page[-1]
        next_cursor = getattr(last, "id", None)
    return {"items": page, "total": total, "next_cursor": next_cursor}


def build_app(service_factory):
    """Build the FastAPI app.

    ``service_factory`` is a zero-arg callable returning an
    :class:`AgentManagementService` (or a facade exposing the same attributes).
    """
    app = FastAPI(title="Agent Management API", version="0.1.0")
    app.add_exception_handler(AgentManagementError, problem_handler)

    @app.get("/health", include_in_schema=False)
    async def health():
        """Liveness probe."""
        return {"status": "ok"}

    def svc():
        return service_factory()

    router = APIRouter(prefix="/api/v1")

    # ------------------------------------------------------------------ providers
    @router.post("/providers", response_model=ProviderResponse, status_code=201)
    async def create_provider(payload: ProviderCreate, service: AgentManagementService = Depends(svc)):
        return await service.providers.create_provider(payload.model_dump())

    @router.get("/providers", response_model=ProviderListResponse)
    async def list_providers(
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0),
        service: AgentManagementService = Depends(svc),
    ):
        rows, total = await service.providers.list_providers(limit=limit, offset=offset)
        return {"items": rows, "total": total}

    @router.get("/providers/types")
    async def provider_types(service: AgentManagementService = Depends(svc)):
        return {"types": service.providers.registry.types()}

    @router.get("/providers/{provider_id}", response_model=ProviderResponse)
    async def get_provider(provider_id: str, service: AgentManagementService = Depends(svc)):
        return await service.providers.get_provider(provider_id)

    @router.patch("/providers/{provider_id}", response_model=ProviderResponse)
    async def update_provider(
        provider_id: str,
        payload: ProviderUpdate,
        service: AgentManagementService = Depends(svc),
    ):
        return await service.providers.update_provider(provider_id, payload.model_dump(exclude_unset=True))

    @router.delete("/providers/{provider_id}", status_code=204)
    async def delete_provider(provider_id: str, service: AgentManagementService = Depends(svc)):
        await service.providers.delete_provider(provider_id)
        return None

    # ------------------------------------------------------------- model profiles
    @router.post("/model-profiles", response_model=ModelProfileResponse, status_code=201)
    async def create_model_profile(payload: ModelProfileCreate, service: AgentManagementService = Depends(svc)):
        return await service.model_profiles.create(payload.model_dump())

    @router.get("/model-profiles", response_model=ModelProfileListResponse)
    async def list_model_profiles(
        provider_id: Optional[str] = None,
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0),
        after: Optional[str] = Query(default=None),
        service: AgentManagementService = Depends(svc),
    ):
        rows, total = await service.model_profiles.list(provider_id=provider_id)
        return _cursor_page(rows, total, limit=limit, offset=offset)

    @router.get("/model-profiles/{profile_id}", response_model=ModelProfileResponse)
    async def get_model_profile(profile_id: str, service: AgentManagementService = Depends(svc)):
        return await service.model_profiles.get(profile_id)

    @router.patch("/model-profiles/{profile_id}", response_model=ModelProfileResponse)
    async def update_model_profile(
        profile_id: str,
        payload: ModelProfileUpdate,
        service: AgentManagementService = Depends(svc),
    ):
        return await service.model_profiles.update(profile_id, payload.model_dump(exclude_unset=True))

    @router.delete("/model-profiles/{profile_id}", status_code=204)
    async def delete_model_profile(profile_id: str, service: AgentManagementService = Depends(svc)):
        await service.model_profiles.delete(profile_id)
        return None

    # -------------------------------------------------------------- tool policies
    @router.post("/tool-policies", response_model=ToolPolicyResponse, status_code=201)
    async def create_tool_policy(payload: ToolPolicyCreate, service: AgentManagementService = Depends(svc)):
        return await service.tool_policies.create(payload.model_dump())

    @router.get("/tool-policies", response_model=ToolPolicyListResponse)
    async def list_tool_policies(
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0),
        after: Optional[str] = Query(default=None),
        service: AgentManagementService = Depends(svc),
    ):
        rows, total = await service.tool_policies.list()
        return _cursor_page(rows, total, limit=limit, offset=offset)

    @router.get("/tool-policies/{policy_id}", response_model=ToolPolicyResponse)
    async def get_tool_policy(policy_id: str, service: AgentManagementService = Depends(svc)):
        return await service.tool_policies.get(policy_id)

    @router.patch("/tool-policies/{policy_id}", response_model=ToolPolicyResponse)
    async def update_tool_policy(
        policy_id: str,
        payload: ToolPolicyUpdate,
        service: AgentManagementService = Depends(svc),
    ):
        return await service.tool_policies.update(policy_id, payload.model_dump(exclude_unset=True))

    @router.delete("/tool-policies/{policy_id}", status_code=204)
    async def delete_tool_policy(policy_id: str, service: AgentManagementService = Depends(svc)):
        await service.tool_policies.delete(policy_id)
        return None

    # ----------------------------------------------------------- agent definitions
    @router.post("/agents/definitions", response_model=AgentDefinitionResponse, status_code=201)
    async def create_agent_definition(payload: AgentDefinitionCreate, service: AgentManagementService = Depends(svc)):
        return await service.agent_definitions.create(payload.model_dump())

    @router.get("/agents/definitions", response_model=AgentDefinitionListResponse)
    async def list_agent_definitions(
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0),
        after: Optional[str] = Query(default=None),
        service: AgentManagementService = Depends(svc),
    ):
        rows, total = await service.agent_definitions.list(limit=limit, offset=offset)
        return _cursor_page(rows, total, limit=limit, offset=offset)

    @router.get("/agents/definitions/{definition_id}", response_model=AgentDefinitionResponse)
    async def get_agent_definition(definition_id: str, service: AgentManagementService = Depends(svc)):
        return await service.agent_definitions.get(definition_id)

    @router.patch("/agents/definitions/{definition_id}", response_model=AgentDefinitionResponse)
    async def update_agent_definition(
        definition_id: str,
        payload: AgentDefinitionUpdate,
        service: AgentManagementService = Depends(svc),
    ):
        return await service.agent_definitions.update(definition_id, payload.model_dump(exclude_unset=True))

    @router.delete("/agents/definitions/{definition_id}", status_code=204)
    async def delete_agent_definition(definition_id: str, service: AgentManagementService = Depends(svc)):
        await service.agent_definitions.delete(definition_id)
        return None

    # ------------------------------------------------------------ agent instances
    @router.post("/agents/instances", response_model=AgentInstanceResponse, status_code=201)
    async def create_agent_instance(payload: AgentInstanceCreate, service: AgentManagementService = Depends(svc)):
        return await service.agent_instances.create(payload.model_dump())

    @router.get("/agents/instances", response_model=AgentInstanceListResponse)
    async def list_agent_instances(
        status: Optional[str] = None,
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0),
        service: AgentManagementService = Depends(svc),
    ):
        rows, total = await service.agent_instances.list(status=status, limit=limit, offset=offset)
        return {"items": rows, "total": total}

    @router.get("/agents/instances/{instance_id}", response_model=AgentInstanceResponse)
    async def get_agent_instance(instance_id: str, service: AgentManagementService = Depends(svc)):
        return await service.agent_instances.get(instance_id)

    @router.post("/agents/instances/{instance_id}/start", response_model=AgentInstanceResponse)
    async def start_agent_instance(instance_id: str, service: AgentManagementService = Depends(svc)):
        return await service.agent_instances.transition(instance_id, "running")

    @router.post("/agents/instances/{instance_id}/complete", response_model=AgentInstanceResponse)
    async def complete_agent_instance(
        instance_id: str,
        payload: Optional[LifecycleAction] = None,
        service: AgentManagementService = Depends(svc),
    ):
        return await service.agent_instances.transition(instance_id, "completed")

    @router.post("/agents/instances/{instance_id}/fail", response_model=AgentInstanceResponse)
    async def fail_agent_instance(
        instance_id: str,
        payload: Optional[LifecycleAction] = None,
        service: AgentManagementService = Depends(svc),
    ):
        return await service.agent_instances.transition(instance_id, "failed")

    @router.post("/agents/instances/{instance_id}/terminate", response_model=AgentInstanceResponse)
    async def terminate_agent_instance(
        instance_id: str,
        payload: Optional[LifecycleAction] = None,
        service: AgentManagementService = Depends(svc),
    ):
        return await service.agent_instances.transition(instance_id, "terminated")

    # --------------------------------------------------------------------- usage
    @router.get("/usage/summary", response_model=UsageSummaryResponse)
    async def usage_summary(service: AgentManagementService = Depends(svc)):
        return await service.usage.summary()

    @router.get("/usage/agents/{agent_instance_id}", response_model=UsageListResponse)
    async def usage_for_agent(
        agent_instance_id: str,
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0),
        service: AgentManagementService = Depends(svc),
    ):
        rows, total = await service.usage.list_for_agent(agent_instance_id, limit=limit, offset=offset)
        return {"items": rows, "total": total}

    # ----------------------------------------------------------------- completion
    @router.post("/completions", response_model=CompleteResponse)
    async def run_completion(payload: CompleteRequest, service: AgentManagementService = Depends(svc)):
        return await service.run_completion(
            provider_id=payload.provider_id,
            model_profile_id=payload.model_profile_id,
            agent_instance_id=payload.agent_instance_id,
            messages=payload.messages,
            temperature=payload.temperature,
            max_tokens=payload.max_tokens,
        )

    app.include_router(router)
    return app