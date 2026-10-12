"""Service layer: validation, state machines and cross-entity invariants.

Layered under the FastAPI router so business logic stays independent of transport.
Persists to SQLAlchemy models, enforces optimistic locking (``version`` column),
maps uniqueness violations to :class:`DuplicateKeyError`, and drives provider
independence via the :class:`ProviderRegistry`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .errors import (
    DuplicateKeyError,
    NotFoundError,
    OptimisticLockError,
    StateTransitionError,
    ValidationError,
)
from .models import (
    AgentDefinition,
    AgentInstance,
    ModelProfile,
    Provider,
    TokenUsage,
    ToolPolicy,
)
from .providers import BaseProvider, ProviderRegistry, get_registry
from .tool_policy import ToolPolicyEngine

MAX_PAGE = 100


# --------------------------------------------------------------------------- cursor pagination helpers
# Implements ADR-101 cursor-based pagination matching orchestration-server/services/cursor.py

def _to_epoch_ms(dt: datetime) -> int:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def encode_cursor(created_at: Optional[datetime], row_id: str) -> str:
    """Build an opaque `next_cursor` from a page's last row."""
    return f"{_to_epoch_ms(created_at) if created_at is not None else 0}:{row_id}"


def decode_cursor(after: Optional[str]) -> Optional[Tuple[datetime, str]]:
    """Parse an ``after`` cursor into ``(created_at, row_id)`` or ``None``."""
    if not after:
        return None
    try:
        ms_str, row_id = after.split(":", 1)
        created_at = datetime.fromtimestamp(int(ms_str) / 1000, tz=timezone.utc)
    except (ValueError, IndexError):
        return None
    return created_at, row_id


def apply_keyset_predicate(
    stmt: select,
    created_at_col: Any,
    row_id_col: Any,
    after: Optional[str],
) -> select:
    """Constrain a query to rows strictly after the cursor position."""
    decoded = decode_cursor(after)
    if decoded is None:
        return stmt
    cursor_at, cursor_id = decoded
    return stmt.where(
        or_(
            created_at_col < cursor_at,
            and_(created_at_col == cursor_at, row_id_col < cursor_id),
        )
    )


def fetch_one_more(stmt: select, limit: int) -> select:
    """Fetch ``limit + 1`` rows so the caller can detect a subsequent page."""
    return stmt.limit(limit + 1)


def split_page(
    rows: List[Any],
    limit: int,
    key_of: callable,
) -> Tuple[List[Any], Optional[str]]:
    """Split ``limit + 1`` fetched rows into ``(page, next_cursor)``.

    ``rows`` are ordered ``(created_at DESC, id DESC)`` and ``key_of(row)``
    returns the row's ``(created_at, id)`` pair.
    """
    has_more = len(rows) > limit
    page = rows[:limit]
    if has_more and page:
        created_at, row_id = key_of(page[-1])
        return page, encode_cursor(created_at, row_id)
    return page, None


# --------------------------------------------------------------------------- helpers


def _check_version(record, expected: Optional[int]) -> None:
    if expected is not None and record.version != expected:
        raise OptimisticLockError(
            f"Resource {record.id} has version {record.version}, expected {expected}"
        )


def _apply_patch(record, patch: Dict[str, Any], allowed: set) -> None:
    for field, value in patch.items():
        if field in allowed and value is not None:
            setattr(record, field, value)
    record.version = (record.version or 1) + 1


class ProviderService:
    def __init__(self, session_factory: async_sessionmaker) -> None:
        self.sf = session_factory
        self.registry: ProviderRegistry = get_registry()

    async def create_provider(self, data: Dict[str, Any]) -> Provider:
        async with self.sf() as session:
            if data.get("type") not in self.registry.types():
                raise ValidationError(
                    f"Unknown provider type '{data.get('type')}'. "
                    f"Known: {', '.join(sorted(self.registry.types())) or 'none'}"
                )
            row = Provider(
                name=data["name"],
                type=data.get("type", "openrouter"),
                base_url=data.get("base_url"),
                auth_config=data.get("auth_config") or {},
                rate_limits=data.get("rate_limits"),
                is_active=data.get("is_active", True),
            )
            session.add(row)
            try:
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                raise DuplicateKeyError(
                    f"Provider name '{data['name']}' already exists"
                ) from exc
            await session.refresh(row)
            return row

    async def get_provider(self, provider_id: str) -> Provider:
        async with self.sf() as session:
            row = await session.get(Provider, provider_id)
            if row is None:
                raise NotFoundError(f"Provider {provider_id} not found")
            return row

    async def list_providers(
        self, limit: int = 50, offset: int = 0, after: Optional[str] = None
    ) -> Tuple[List[Provider], int, Optional[str]]:
        limit = min(max(limit, 1), MAX_PAGE)
        async with self.sf() as session:
            total = (
                await session.execute(select(func.count()).select_from(Provider))
            ).scalar_one()
            stmt = select(Provider).order_by(Provider.created_at.desc(), Provider.id.desc())
            stmt = apply_keyset_predicate(stmt, Provider.created_at, Provider.id, after)
            stmt = fetch_one_more(stmt, limit)
            rows = (await session.execute(stmt)).scalars().all()
            page, next_cursor = split_page(list(rows), limit, lambda r: (r.created_at, r.id))
            return page, total, next_cursor

    async def update_provider(self, provider_id: str, patch: Dict[str, Any]) -> Provider:
        allowed = {"name", "base_url", "auth_config", "rate_limits", "is_active"}
        async with self.sf() as session:
            row = await session.get(Provider, provider_id)
            if row is None:
                raise NotFoundError(f"Provider {provider_id} not found")
            _check_version(row, patch.pop("version", None))
            _apply_patch(row, patch, allowed)
            try:
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                raise DuplicateKeyError("Provider name already in use") from exc
            await session.refresh(row)
            return row

    async def delete_provider(self, provider_id: str) -> None:
        async with self.sf() as session:
            row = await session.get(Provider, provider_id)
            if row is None:
                raise NotFoundError(f"Provider {provider_id} not found")
            await session.delete(row)
            await session.commit()

    def build_adapter(
        self,
        provider: Provider,
        model: Optional[str] = None,
        client_factory: Any = None,
    ) -> BaseProvider:
        """Resolve a provider DB record into a concrete adapter.

        The config dict is built from ``auth_config``, the persisted ``base_url``
        and an optional model id, then passed to the registry builder. Business
        logic never names a concrete adapter class here.
        """
        config: Dict[str, Any] = dict(provider.auth_config or {})
        if provider.base_url:
            config["base_url"] = provider.base_url
        if model:
            config["model"] = model
        adapter_cls = self.registry.get(provider.type)
        return adapter_cls(config, **({"client_factory": client_factory} if client_factory else {}))


class ModelProfileService:
    def __init__(self, session_factory: async_sessionmaker) -> None:
        self.sf = session_factory

    async def create(self, data: Dict[str, Any]) -> ModelProfile:
        async with self.sf() as session:
            provider = await session.get(Provider, data["provider_id"])
            if provider is None:
                raise NotFoundError(f"Provider {data['provider_id']} not found")
            row = ModelProfile(**{k: v for k, v in data.items() if v is not None})
            if row.is_default:
                await self._clear_defaults(session, data["provider_id"])
            session.add(row)
            try:
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                raise DuplicateKeyError(
                    f"Model profile '{data['name']}' already exists for this provider"
                ) from exc
            await session.refresh(row)
            return row

    @staticmethod
    async def _clear_defaults(session: AsyncSession, provider_id: str) -> None:
        await session.execute(
            update(ModelProfile)
            .where(ModelProfile.provider_id == provider_id, ModelProfile.is_default.is_(True))
            .values(is_default=False)
        )

    async def get(self, profile_id: str) -> ModelProfile:
        async with self.sf() as session:
            row = await session.get(ModelProfile, profile_id)
            if row is None:
                raise NotFoundError(f"Model profile {profile_id} not found")
            return row

    async def list(
        self,
        provider_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
        after: Optional[str] = None,
    ) -> Tuple[List[ModelProfile], int, Optional[str]]:
        limit = min(max(limit, 1), MAX_PAGE)
        async with self.sf() as session:
            query = select(ModelProfile)
            if provider_id:
                query = query.where(ModelProfile.provider_id == provider_id)
            total = (
                await session.execute(select(func.count()).select_from(query.subquery()))
            ).scalar_one()
            stmt = query.order_by(ModelProfile.created_at.desc(), ModelProfile.id.desc())
            stmt = apply_keyset_predicate(stmt, ModelProfile.created_at, ModelProfile.id, after)
            stmt = fetch_one_more(stmt, limit)
            rows = (await session.execute(stmt)).scalars().all()
            page, next_cursor = split_page(list(rows), limit, lambda r: (r.created_at, r.id))
            return page, total, next_cursor

    async def update(self, profile_id: str, patch: Dict[str, Any]) -> ModelProfile:
        allowed = {
            "name", "model_id", "display_name", "parameters", "context_window",
            "cost_per_1k_input", "cost_per_1k_output", "capabilities", "is_default",
        }
        async with self.sf() as session:
            row = await session.get(ModelProfile, profile_id)
            if row is None:
                raise NotFoundError(f"Model profile {profile_id} not found")
            _check_version(row, patch.pop("version", None))
            if patch.get("is_default"):
                await self._clear_defaults(session, row.provider_id)
            _apply_patch(row, patch, allowed)
            try:
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                raise DuplicateKeyError("Model profile name already in use for provider") from exc
            await session.refresh(row)
            return row

    async def delete(self, profile_id: str) -> None:
        async with self.sf() as session:
            row = await session.get(ModelProfile, profile_id)
            if row is None:
                raise NotFoundError(f"Model profile {profile_id} not found")
            await session.delete(row)
            await session.commit()

    async def resolve_default(self, provider_id: str) -> Optional[ModelProfile]:
        async with self.sf() as session:
            row = (
                await session.execute(
                    select(ModelProfile)
                    .where(ModelProfile.provider_id == provider_id)
                    .order_by(ModelProfile.is_default.desc(), ModelProfile.created_at)
                )
            ).scalars().first()
            return row


class ToolPolicyService:
    def __init__(self, session_factory: async_sessionmaker) -> None:
        self.sf = session_factory
        self.engine = ToolPolicyEngine()

    async def create(self, data: Dict[str, Any]) -> ToolPolicy:
        from .tool_policy import normalize_policy

        permissions = normalize_policy(data.get("permissions") or {})
        async with self.sf() as session:
            row = ToolPolicy(
                name=data["name"],
                description=data.get("description"),
                permissions=permissions,
                is_default=data.get("is_default", False),
            )
            session.add(row)
            try:
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                raise DuplicateKeyError(f"Tool policy '{data['name']}' already exists") from exc
            await session.refresh(row)
            return row

    async def get(self, policy_id: str) -> ToolPolicy:
        async with self.sf() as session:
            row = await session.get(ToolPolicy, policy_id)
            if row is None:
                raise NotFoundError(f"Tool policy {policy_id} not found")
            return row

    async def list(
        self,
        limit: int = 50,
        offset: int = 0,
        after: Optional[str] = None,
    ) -> Tuple[List[ToolPolicy], int, Optional[str]]:
        limit = min(max(limit, 1), MAX_PAGE)
        async with self.sf() as session:
            query = select(ToolPolicy)
            total = (
                await session.execute(select(func.count()).select_from(query.subquery()))
            ).scalar_one()
            stmt = query.order_by(ToolPolicy.created_at.desc(), ToolPolicy.id.desc())
            stmt = apply_keyset_predicate(stmt, ToolPolicy.created_at, ToolPolicy.id, after)
            stmt = fetch_one_more(stmt, limit)
            rows = (await session.execute(stmt)).scalars().all()
            page, next_cursor = split_page(list(rows), limit, lambda r: (r.created_at, r.id))
            return page, total, next_cursor

    async def update(self, policy_id: str, patch: Dict[str, Any]) -> ToolPolicy:
        allowed = {"name", "description", "permissions", "is_default"}
        async with self.sf() as session:
            row = await session.get(ToolPolicy, policy_id)
            if row is None:
                raise NotFoundError(f"Tool policy {policy_id} not found")
            _check_version(row, patch.pop("version", None))
            _apply_patch(row, patch, allowed)
            try:
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                raise DuplicateKeyError("Tool policy name already in use") from exc
            await session.refresh(row)
            return row

    async def delete(self, policy_id: str) -> None:
        async with self.sf() as session:
            row = await session.get(ToolPolicy, policy_id)
            if row is None:
                raise NotFoundError(f"Tool policy {policy_id} not found")
            await session.delete(row)
            await session.commit()


class AgentDefinitionService:
    def __init__(self, session_factory: async_sessionmaker) -> None:
        self.sf = session_factory

    async def create(self, data: Dict[str, Any]) -> AgentDefinition:
        async with self.sf() as session:
            await self._validate_refs(session, data)
            row = AgentDefinition(**{k: v for k, v in data.items() if v is not None})
            session.add(row)
            try:
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                raise DuplicateKeyError(f"Agent definition '{data['name']}' already exists") from exc
            await session.refresh(row)
            return row

    @staticmethod
    async def _validate_refs(session: AsyncSession, data: Dict[str, Any]) -> None:
        mp = data.get("default_model_profile_id")
        if mp and await session.get(ModelProfile, mp) is None:
            raise NotFoundError(f"Model profile {mp} not found")
        tp = data.get("default_tool_policy_id")
        if tp and await session.get(ToolPolicy, tp) is None:
            raise NotFoundError(f"Tool policy {tp} not found")

    async def get(self, definition_id: str) -> AgentDefinition:
        async with self.sf() as session:
            row = await session.get(AgentDefinition, definition_id)
            if row is None:
                raise NotFoundError(f"Agent definition {definition_id} not found")
            return row

    async def list(
        self,
        limit: int = 50,
        offset: int = 0,
        after: Optional[str] = None,
    ) -> Tuple[List[AgentDefinition], int, Optional[str]]:
        limit = min(max(limit, 1), MAX_PAGE)
        async with self.sf() as session:
            total = (
                await session.execute(select(func.count()).select_from(AgentDefinition))
            ).scalar_one()
            stmt = select(AgentDefinition).order_by(AgentDefinition.created_at.desc(), AgentDefinition.id.desc())
            stmt = apply_keyset_predicate(stmt, AgentDefinition.created_at, AgentDefinition.id, after)
            stmt = fetch_one_more(stmt, limit)
            rows = (await session.execute(stmt)).scalars().all()
            page, next_cursor = split_page(list(rows), limit, lambda r: (r.created_at, r.id))
            return page, total, next_cursor

    async def update(self, definition_id: str, patch: Dict[str, Any]) -> AgentDefinition:
        allowed = {
            "name", "description", "system_prompt", "default_model_profile_id",
            "default_tool_policy_id", "capabilities", "config_schema",
        }
        async with self.sf() as session:
            row = await session.get(AgentDefinition, definition_id)
            if row is None:
                raise NotFoundError(f"Agent definition {definition_id} not found")
            await self._validate_refs(session, patch)
            _check_version(row, patch.pop("version", None))
            _apply_patch(row, patch, allowed)
            try:
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                raise DuplicateKeyError("Agent definition name already in use") from exc
            await session.refresh(row)
            return row

    async def delete(self, definition_id: str) -> None:
        async with self.sf() as session:
            row = await session.get(AgentDefinition, definition_id)
            if row is None:
                raise NotFoundError(f"Agent definition {definition_id} not found")
            await session.delete(row)
            await session.commit()

    async def get_or_create_inline(self, name: str, system_prompt: Optional[str]) -> AgentDefinition:
        """Create a transient definition from inline instance data if not provided."""
        return await self.create(
            {
                "name": name or "inline-agent",
                "description": "Created from inline instance config",
                "system_prompt": system_prompt,
            }
        )


class AgentInstanceService:
    def __init__(self, session_factory: async_sessionmaker) -> None:
        self.sf = session_factory

    async def create(self, data: Dict[str, Any]) -> AgentInstance:
        async with self.sf() as session:
            def_id = data.get("agent_definition_id")
            definition = await session.get(AgentDefinition, def_id) if def_id else None
            if definition is None:
                # Either a bad id, or an inline definition was supplied.
                raise NotFoundError(
                    f"Agent definition {def_id} not found" if def_id else "agent_definition_id is required"
                )
            model_profile_id = data.get("model_profile_id") or definition.default_model_profile_id
            tool_policy_id = data.get("tool_policy_id") or definition.default_tool_policy_id
            if model_profile_id and await session.get(ModelProfile, model_profile_id) is None:
                raise NotFoundError(f"Model profile {model_profile_id} not found")
            if tool_policy_id and await session.get(ToolPolicy, tool_policy_id) is None:
                raise NotFoundError(f"Tool policy {tool_policy_id} not found")
            row = AgentInstance(
                agent_definition_id=definition.id,
                model_profile_id=model_profile_id,
                tool_policy_id=tool_policy_id,
                status="pending",
                runtime_config=data.get("runtime_config") or {},
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row

    async def get(self, instance_id: str) -> AgentInstance:
        async with self.sf() as session:
            row = await session.get(AgentInstance, instance_id)
            if row is None:
                raise NotFoundError(f"Agent instance {instance_id} not found")
            return row

    async def list(
        self,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
        after: Optional[str] = None,
    ) -> Tuple[List[AgentInstance], int, Optional[str]]:
        limit = min(max(limit, 1), MAX_PAGE)
        async with self.sf() as session:
            query = select(AgentInstance)
            if status:
                query = query.where(AgentInstance.status == status)
            total = (
                await session.execute(select(func.count()).select_from(query.subquery()))
            ).scalar_one()
            stmt = query.order_by(AgentInstance.created_at.desc(), AgentInstance.id.desc())
            stmt = apply_keyset_predicate(stmt, AgentInstance.created_at, AgentInstance.id, after)
            stmt = fetch_one_more(stmt, limit)
            rows = (await session.execute(stmt)).scalars().all()
            page, next_cursor = split_page(list(rows), limit, lambda r: (r.created_at, r.id))
            return page, total, next_cursor

    async def transition(
        self, instance_id: str, to_status: str, *, version: Optional[int] = None
    ) -> AgentInstance:
        allowed = {
            ("pending", "running"),
            ("running", "completed"),
            ("running", "failed"),
            ("pending", "terminated"),
            ("running", "terminated"),
            ("failed", "running"),
        }
        async with self.sf() as session:
            row = await session.get(AgentInstance, instance_id)
            if row is None:
                raise NotFoundError(f"Agent instance {instance_id} not found")
            _check_version(row, version)
            if (row.status, to_status) not in allowed:
                raise StateTransitionError(
                    f"Cannot transition agent instance from '{row.status}' to '{to_status}'"
                )
            row.status = to_status
            if to_status == "running" and row.started_at is None:
                row.started_at = _now()
            if to_status in ("completed", "failed", "terminated"):
                row.completed_at = _now()
            row.version += 1
            await session.commit()
            await session.refresh(row)
            return row


def _now():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)


class TokenUsageService:
    def __init__(self, session_factory: async_sessionmaker) -> None:
        self.sf = session_factory

    async def record(
        self,
        *,
        usage,
        agent_instance_id: Optional[str] = None,
        provider_id: Optional[str] = None,
        model_profile_id: Optional[str] = None,
        model: Optional[str] = None,
        request_id: Optional[str] = None,
        cost: float = 0.0,
        currency: str = "USD",
    ) -> TokenUsage:
        async with self.sf() as session:
            row = TokenUsage(
                agent_instance_id=agent_instance_id,
                provider_id=provider_id,
                model_profile_id=model_profile_id,
                model=model,
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens,
                total_tokens=usage.total_tokens,
                est_cost=cost,
                currency=currency,
                request_id=request_id,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row

    async def list_for_agent(
        self, agent_instance_id: str, limit: int = 50, offset: int = 0
    ) -> Tuple[List[TokenUsage], int]:
        limit = min(max(limit, 1), MAX_PAGE)
        async with self.sf() as session:
            query = (
                select(TokenUsage)
                .where(TokenUsage.agent_instance_id == agent_instance_id)
            )
            total = (
                await session.execute(select(func.count()).select_from(query.subquery()))
            ).scalar_one()
            rows = (
                await session.execute(
                    query.order_by(TokenUsage.created_at).limit(limit).offset(offset)
                )
            ).scalars().all()
            return list(rows), total

    async def summary(self) -> Dict[str, Any]:
        async with self.sf() as session:
            counts = (
                await session.execute(
                    select(
                        func.coalesce(func.sum(TokenUsage.prompt_tokens), 0),
                        func.coalesce(func.sum(TokenUsage.completion_tokens), 0),
                        func.coalesce(func.sum(TokenUsage.total_tokens), 0),
                        func.coalesce(func.sum(TokenUsage.est_cost), 0.0),
                        func.count(),
                    )
                )
            ).one()
            by_model = await self._group(session, TokenUsage.model)
            by_provider = await self._group(session, TokenUsage.provider_id)
            return {
                "total_prompt_tokens": int(counts[0]),
                "total_completion_tokens": int(counts[1]),
                "total_tokens": int(counts[2]),
                "total_est_cost": float(counts[3]),
                "request_count": int(counts[4]),
                "by_model": by_model,
                "by_provider": by_provider,
            }

    @staticmethod
    async def _group(session: AsyncSession, attr) -> Dict[str, Dict[str, Any]]:
        rows = (
            await session.execute(
                select(
                    attr,
                    func.sum(TokenUsage.prompt_tokens),
                    func.sum(TokenUsage.completion_tokens),
                    func.sum(TokenUsage.total_tokens),
                    func.sum(TokenUsage.est_cost),
                ).group_by(attr)
            )
        ).all()
        return {
            (str(k) if k is not None else "unknown"): {
                "prompt_tokens": int(p),
                "completion_tokens": int(c),
                "total_tokens": int(t),
                "est_cost": float(cost),
            }
            for k, p, c, t, cost in rows
        }


class AgentManagementService:
    """Facade tying provider, agent and usage services into one dependency."""

    def __init__(self, session_factory: async_sessionmaker) -> None:
        self.sf = session_factory
        self.providers = ProviderService(session_factory)
        self.model_profiles = ModelProfileService(session_factory)
        self.tool_policies = ToolPolicyService(session_factory)
        self.agent_definitions = AgentDefinitionService(session_factory)
        self.agent_instances = AgentInstanceService(session_factory)
        self.usage = TokenUsageService(session_factory)

    async def run_completion(
        self,
        *,
        provider_id: str,
        messages: List[Dict[str, str]],
        model_profile_id: Optional[str] = None,
        agent_instance_id: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        client_factory: Any = None,
    ) -> Dict[str, Any]:
        """Run a completion through the provider abstraction and record usage.

        Resolves the model profile (or provider default), builds the adapter, calls
        ``complete``, then persists a :class:`TokenUsage` row so accounting is single
        source of truth. Returns the content + usage + recorded usage id.
        """
        if agent_instance_id:
            instance = await self.agent_instances.get(agent_instance_id)
            if instance.status not in ("running", "failed"):
                raise StateTransitionError(
                    f"Agent instance must be running to complete; status={instance.status}"
                )
        provider = await self.providers.get_provider(provider_id)
        if not provider.is_active:
            from .errors import BusinessRuleError

            raise BusinessRuleError(f"Provider '{provider.name}' is inactive")

        profile = None
        if model_profile_id:
            profile = await self.model_profiles.get(model_profile_id)
            if profile.provider_id != provider.id:
                from .errors import ValidationError as _VE

                raise _VE("model_profile does not belong to the given provider")
        else:
            profile = await self.model_profiles.resolve_default(provider.id)

        model = profile.model_id if profile else None
        adapter = self.providers.build_adapter(provider, model=model, client_factory=client_factory)
        try:
            result = await adapter.complete(
                messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        finally:
            await adapter.close()

        cost = self._estimate_cost(profile, result.usage.prompt_tokens, result.usage.completion_tokens)
        recorded = None
        if agent_instance_id:
            rec = await self.usage.record(
                usage=result.usage,
                agent_instance_id=agent_instance_id,
                provider_id=provider.id,
                model_profile_id=profile.id if profile else None,
                model=result.model or model,
                request_id=result.metadata.get("id"),
                cost=cost,
            )
            recorded = rec.id
        return {
            "content": result.content,
            "model": result.model or model,
            "prompt_tokens": result.usage.prompt_tokens,
            "completion_tokens": result.usage.completion_tokens,
            "total_tokens": result.usage.total_tokens,
            "est_cost": cost,
            "usage_record_id": recorded,
        }

    @staticmethod
    def _estimate_cost(profile, prompt_tokens: int, completion_tokens: int) -> float:
        if profile is None:
            return 0.0
        return round(
            (prompt_tokens / 1000.0) * profile.cost_per_1k_input
            + (completion_tokens / 1000.0) * profile.cost_per_1k_output,
            6,
        )