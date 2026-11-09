"""Service layer: validation, state machines and cross-entity invariants.

Layered under the FastAPI router so business logic stays independent of transport.
Persists to SQLAlchemy models, enforces optimistic locking (``version`` column),
maps uniqueness violations to :class:`DuplicateKeyError`, and drives provider
independence via the :class:`ProviderRegistry`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR
import json
import math
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import and_, func, or_, select, text as sql_text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .errors import (
    BusinessRuleError,
    DuplicateKeyError,
    NotFoundError,
    OptimisticLockError,
    StateTransitionError,
    ValidationError,
)
from .models import (
    AgentBudgetReservation,
    AgentDefinition,
    AgentExecutionBinding,
    AgentInstance,
    ModelProfile,
    Provider,
    TokenUsage,
    ToolPolicy,
)
from .crypto import decrypt_auth_config, encrypt_auth_config
from .providers import BaseProvider, ProviderRegistry, get_registry
from .tool_policy import INDEPENDENT_QA_ROLES, ToolPolicyEngine, normalize_policy, role_accepts_policy

MAX_PAGE = 100
# Historic callers could persist arbitrary runtime_config JSON, including this
# name. Never treat that JSON as a trusted binding; only the dedicated SQL table
# is authoritative. Reject the reserved name for new requests as well.
_EXECUTION_BINDING_KEY = "_execution_binding_v1"


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


async def _apply_patch(session: AsyncSession, record: Any, patch: Dict[str, Any], allowed: set) -> None:
    """Atomic compare-and-swap revision update, even without client If-Match.

    Read/modify/write ORM commits can produce two different configurations with
    the same revision. A SQL version predicate and DB-side increment prevents
    that ABA condition for provider/model/policy/agent profile fences.
    """
    model = type(record)
    values = {field: value for field, value in patch.items()
              if field in allowed and value is not None}
    values["version"] = model.version + 1
    result = await session.execute(
        update(model)
        .where(model.id == record.id, model.version == record.version)
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        raise OptimisticLockError("Profile was updated concurrently; retry from latest revision")


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
                auth_config=encrypt_auth_config(data.get("auth_config") or {}),
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
            if "auth_config" in patch and patch["auth_config"] is not None:
                # Re-encrypt with a fresh DEK whenever auth_config is rewritten.
                patch = dict(patch)
                patch["auth_config"] = encrypt_auth_config(patch["auth_config"])
            try:
                await _apply_patch(session, row, patch, allowed)
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
        config: Dict[str, Any] = dict(decrypt_auth_config(provider.auth_config or {}))
        if provider.base_url:
            config["base_url"] = provider.base_url
        if model:
            config["model"] = model
        adapter_cls = self.registry.get(provider.type)
        return adapter_cls(config, **({"client_factory": client_factory} if client_factory else {}))


def _validate_model_prices(data: Dict[str, Any]) -> None:
    for field in ("cost_per_1k_input", "cost_per_1k_output"):
        if field in data and data[field] is not None:
            value = data[field]
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise ValidationError("Model pricing must be finite and nonnegative")


class ModelProfileService:
    def __init__(self, session_factory: async_sessionmaker) -> None:
        self.sf = session_factory

    async def create(self, data: Dict[str, Any]) -> ModelProfile:
        _validate_model_prices(data)
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
    async def _clear_defaults(
        session: AsyncSession, provider_id: str, *, exclude_id: str | None = None
    ) -> None:
        stmt = update(ModelProfile).where(
            ModelProfile.provider_id == provider_id,
            ModelProfile.is_default.is_(True),
        )
        if exclude_id is not None:
            stmt = stmt.where(ModelProfile.id != exclude_id)
        await session.execute(stmt.values(
            is_default=False, version=ModelProfile.version + 1
        ))

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
        _validate_model_prices(patch)
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
                await self._clear_defaults(session, row.provider_id, exclude_id=row.id)
            try:
                await _apply_patch(session, row, patch, allowed)
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


async def _serialize_role_policy_write(session: AsyncSession) -> None:
    """SQLite writer reservation before reads (Postgres uses explicit row locks).

    The invariant spans policy permissions, definition role and instance
    overrides; CAS on just one row is not enough for concurrent writers.
    """
    if session.get_bind().dialect.name == "sqlite":
        await session.execute(sql_text("BEGIN IMMEDIATE"))


def _ordered_policy_ids(ids: list[str | None]) -> list[str]:
    """Global stable order prevents crossed default/override policy deadlocks."""
    return sorted({policy_id for policy_id in ids if policy_id})


def _require_qa_safe_policy(role: str, policy: ToolPolicy | None) -> None:
    """Fail closed at the API/service boundary; front-end filtering is advisory."""
    if policy is not None and not role_accepts_policy(role, policy.permissions):
        raise BusinessRuleError(
            "Independent tester/reviewer/security role requires a read-only tool policy"
        )


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
            await _serialize_role_policy_write(session)
            row = (await session.execute(
                select(ToolPolicy).where(ToolPolicy.id == policy_id).with_for_update()
            )).scalar_one_or_none()
            if row is None:
                raise NotFoundError(f"Tool policy {policy_id} not found")
            _check_version(row, patch.pop("version", None))
            if patch.get("permissions") is not None:
                patch = dict(patch)
                patch["permissions"] = normalize_policy(patch["permissions"])
                if not role_accepts_policy("reviewer", patch["permissions"]):
                    # Also cover per-instance policy overrides: an API caller
                    # cannot widen a policy already assigned to independent QA.
                    profile = (await session.execute(
                        select(AgentDefinition.id).where(
                            AgentDefinition.default_tool_policy_id == row.id,
                            AgentDefinition.role.in_(INDEPENDENT_QA_ROLES),
                        ).limit(1)
                    )).scalar_one_or_none()
                    instance = (await session.execute(
                        select(AgentInstance.id)
                        .join(AgentDefinition, AgentInstance.agent_definition_id == AgentDefinition.id)
                        .where(
                            AgentInstance.tool_policy_id == row.id,
                            AgentDefinition.role.in_(INDEPENDENT_QA_ROLES),
                        ).limit(1)
                    )).scalar_one_or_none()
                    if profile is not None or instance is not None:
                        raise BusinessRuleError(
                            "Cannot widen a tool policy assigned to an independent QA role"
                        )
            try:
                await _apply_patch(session, row, patch, allowed)
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


def _profile_storage(data: Dict[str, Any]) -> Dict[str, Any]:
    """Serialize structured profile lists into existing SQL text columns.

    Retains existing DB schema and avoids an implicit migration on live SQLite.
    """
    import json

    data = dict(data)
    for field in ("supported_stages", "skills"):
        value = data.get(field)
        if value is not None:
            if (type(value) is not list or len(value) > 32
                    or any(type(item) is not str or not 1 <= len(item) <= 64 for item in value)):
                raise ValueError("Invalid bounded agent profile list")
            data[field] = json.dumps(value)
    return data


class AgentDefinitionService:
    def __init__(self, session_factory: async_sessionmaker) -> None:
        self.sf = session_factory

    async def create(self, data: Dict[str, Any]) -> AgentDefinition:
        async with self.sf() as session:
            await _serialize_role_policy_write(session)
            await self._validate_refs(session, data)
            data = _profile_storage(data)
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
    async def _validate_refs(
        session: AsyncSession, data: Dict[str, Any],
        current: AgentDefinition | None = None,
    ) -> None:
        mp = data.get("default_model_profile_id")
        if mp and await session.get(ModelProfile, mp) is None:
            raise NotFoundError(f"Model profile {mp} not found")
        tp = data.get("default_tool_policy_id") or (
            current.default_tool_policy_id if current else None
        )
        role = data.get("role") or (current.role if current else "generalist")
        overrides: list[str | None] = []
        if current is not None and role in INDEPENDENT_QA_ROLES:
            # Definition rows are locked by the caller, so new instance
            # overrides cannot appear while collecting the policy set.
            overrides = list((await session.execute(
                select(AgentInstance.tool_policy_id).where(
                    AgentInstance.agent_definition_id == current.id,
                    AgentInstance.tool_policy_id.is_not(None),
                )
            )).scalars().all())
        # Do NOT lock default first and overrides later: two different
        # definitions may have the opposite P/Q pair and deadlock on PG.
        for policy_id in _ordered_policy_ids([tp, *overrides]):
            policy = (await session.execute(
                select(ToolPolicy).where(ToolPolicy.id == policy_id)
                .with_for_update()
            )).scalar_one_or_none()
            if policy is None:
                raise NotFoundError("Assigned tool policy unavailable")
            _require_qa_safe_policy(role, policy)

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
            "role", "max_concurrency", "budget_limit", "supported_stages", "skills",
        }
        async with self.sf() as session:
            await _serialize_role_policy_write(session)
            row = (await session.execute(
                select(AgentDefinition).where(AgentDefinition.id == definition_id)
                .with_for_update()
            )).scalar_one_or_none()
            if row is None:
                raise NotFoundError(f"Agent definition {definition_id} not found")
            await self._validate_refs(session, patch, current=row)
            _check_version(row, patch.pop("version", None))
            try:
                await _apply_patch(session, row, _profile_storage(patch), allowed)
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
            await _serialize_role_policy_write(session)
            def_id = data.get("agent_definition_id")
            definition = (await session.execute(
                select(AgentDefinition).where(AgentDefinition.id == def_id).with_for_update()
            )).scalar_one_or_none() if def_id else None
            if definition is None:
                # Either a bad id, or an inline definition was supplied.
                raise NotFoundError(
                    f"Agent definition {def_id} not found" if def_id else "agent_definition_id is required"
                )
            model_profile_id = data.get("model_profile_id") or definition.default_model_profile_id
            tool_policy_id = data.get("tool_policy_id") or definition.default_tool_policy_id
            model_profile = (
                await session.get(ModelProfile, model_profile_id) if model_profile_id else None
            )
            tool_policy = (await session.execute(
                select(ToolPolicy).where(ToolPolicy.id == tool_policy_id).with_for_update()
            )).scalar_one_or_none() if tool_policy_id else None
            if model_profile_id and model_profile is None:
                raise NotFoundError(f"Model profile {model_profile_id} not found")
            if tool_policy_id and tool_policy is None:
                raise NotFoundError(f"Tool policy {tool_policy_id} not found")
            _require_qa_safe_policy(definition.role, tool_policy)
            provider = (
                await session.get(Provider, model_profile.provider_id) if model_profile else None
            )
            if model_profile and (provider is None or not provider.is_active):
                raise BusinessRuleError("Agent instance model provider is unavailable")
            runtime_config = dict(data.get("runtime_config") or {})
            if _EXECUTION_BINDING_KEY in runtime_config:
                raise ValidationError("Reserved runtime configuration field")
            row = AgentInstance(
                agent_definition_id=definition.id,
                model_profile_id=model_profile_id,
                tool_policy_id=tool_policy_id,
                status="pending",
                runtime_config=runtime_config,
            )
            session.add(row)
            await session.flush()
            # Only this control-plane write creates the SQL binding. Older
            # instances have no row, even if their JSON forged this key.
            session.add(AgentExecutionBinding(
                agent_instance_id=row.id,
                definition_version=definition.version,
                model_version=model_profile.version if model_profile else None,
                policy_version=tool_policy.version if tool_policy else None,
                provider_id=provider.id if provider else None,
                provider_version=provider.version if provider else None,
            ))
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
            if to_status == "running" and session.get_bind().dialect.name == "sqlite":
                # SQLite ignores SELECT FOR UPDATE. Acquire a writer reservation
                # before reading any state so two starts cannot both observe a
                # free slot on separate connections/processes.
                await session.execute(sql_text("BEGIN IMMEDIATE"))
            row = await session.get(AgentInstance, instance_id)
            if row is None:
                raise NotFoundError(f"Agent instance {instance_id} not found")
            if to_status == "running":
                # On PostgreSQL this row lock serializes admission with other
                # starts and profile capacity edits. SQLite's BEGIN IMMEDIATE
                # serializes writers for the full transaction instead.
                definition = (
                    await session.execute(
                        select(AgentDefinition)
                        .where(AgentDefinition.id == row.agent_definition_id)
                        .with_for_update()
                    )
                ).scalar_one_or_none()
                if definition is None:
                    raise NotFoundError("Agent definition unavailable")
                await session.refresh(row)
            _check_version(row, version)
            if (row.status, to_status) not in allowed:
                raise StateTransitionError(
                    f"Cannot transition agent instance from '{row.status}' to '{to_status}'"
                )
            if to_status == "running":
                active = (
                    await session.execute(
                        select(func.count(AgentInstance.id)).where(
                            AgentInstance.agent_definition_id == row.agent_definition_id,
                            AgentInstance.status == "running",
                        )
                    )
                ).scalar_one()
                if active >= definition.max_concurrency:
                    raise BusinessRuleError("Agent profile max_concurrency reached")
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
        budget_reservation_id: Optional[str] = None,
    ) -> TokenUsage:
        async with self.sf() as session:
            if budget_reservation_id is not None:
                # Settlement and admission MUST hold the same definition lock.
                # Otherwise a READ COMMITTED reader can count old usage before
                # the insert and no reservation after its deletion.
                if session.get_bind().dialect.name == "sqlite":
                    await session.execute(sql_text("BEGIN IMMEDIATE"))
                instance = (
                    await session.get(AgentInstance, agent_instance_id)
                    if agent_instance_id is not None else None
                )
                if instance is None:
                    raise BusinessRuleError("Budget reservation missing or mismatched")
                definition = (
                    await session.execute(
                        select(AgentDefinition)
                        .where(AgentDefinition.id == instance.agent_definition_id)
                        .with_for_update()
                    )
                ).scalar_one_or_none()
                reservation = await session.get(AgentBudgetReservation, budget_reservation_id)
                if (
                    definition is None or reservation is None
                    or reservation.agent_definition_id != instance.agent_definition_id
                ):
                    raise BusinessRuleError("Budget reservation missing or mismatched")
                # Removing the reservation and recording actual usage happen
                # in this same locked SQL transaction.
                await session.delete(reservation)
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

    @staticmethod
    def _microusd(profile: ModelProfile, prompt_tokens: int, completion_tokens: int) -> int:
        """Round positive USD estimates upward to microdollar precision."""
        if any(type(n) is not int or n < 0 or n > 1_000_000
               for n in (prompt_tokens, completion_tokens)):
            raise BusinessRuleError("Budget requires bounded nonnegative token limits")
        try:
            incoming = Decimal(str(profile.cost_per_1k_input))
            outgoing = Decimal(str(profile.cost_per_1k_output))
            if not incoming.is_finite() or not outgoing.is_finite() or incoming < 0 or outgoing < 0:
                raise ValueError("Negative or nonfinite model rates")
            amount = (incoming * prompt_tokens + outgoing * completion_tokens) * Decimal(1000)
            if not amount.is_finite() or amount < 0 or amount > Decimal(10**15):
                raise ValueError("Invalid estimated cost")
            return int(amount.to_integral_value(rounding=ROUND_CEILING))
        except (InvalidOperation, ValueError, OverflowError):
            raise BusinessRuleError("Budget pricing configuration unavailable") from None

    @staticmethod
    def _prompt_upper_bound(messages: List[Dict[str, str]]) -> int:
        """Pessimistic byte-level envelope, including roles and protocol margin.

        This is an offline request-size guard, NOT a certified tokenizer or a
        promise about actual provider invoices. The model/provider must still
        enforce configured context limits at execution.
        """
        return sum(
            len(json.dumps(m, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) + 32
            for m in messages
        )

    async def _reserve_estimated_budget(
        self, *, instance: AgentInstance, binding: AgentExecutionBinding,
        profile: ModelProfile, max_tokens: Optional[int],
        messages: List[Dict[str, str]], provider: Provider,
    ) -> str | None:
        """Reserve a pessimistic estimated API cost across all profile instances.

        A persisted outstanding reservation is never auto-released on provider
        errors or process crash: billed side effects may be ambiguous. Operators
        reconcile any such reservation before re-enabling capacity.
        """
        async with self.sf() as session:
            if session.get_bind().dialect.name == "sqlite":
                await session.execute(sql_text("BEGIN IMMEDIATE"))
            definition = (
                await session.execute(
                    select(AgentDefinition)
                    .where(AgentDefinition.id == instance.agent_definition_id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if definition is None or definition.version != binding.definition_version:
                raise BusinessRuleError("Agent definition changed; recreate instance")
            if definition.budget_limit is None:
                return None
            # The OpenAI-compatible adapter forwards provider-owned
            # auth_config.parameters into its completion payload. n > 1
            # multiplies output token cost even when max_tokens is bounded.
            # Fail closed rather than silently reserving only one choice.
            provider_params = decrypt_auth_config(provider.auth_config or {}).get("parameters") or {}
            if not isinstance(provider_params, dict):
                raise BusinessRuleError("Budgeted provider parameters invalid")
            # The HTTP adapter forwards arbitrary provider parameters into
            # its payload. Prompt-bearing schemas/functions or vendor-specific
            # hidden prompts are impossible to budget from just messages.
            safe_scalars = {
                "n", "temperature", "top_p", "presence_penalty",
                "frequency_penalty", "seed",
            }
            if any(
                key not in safe_scalars or type(value) not in (int, float)
                or not math.isfinite(value)
                for key, value in provider_params.items()
            ):
                raise BusinessRuleError("Budgeted provider parameters may not add prompt content")
            n = provider_params.get("n", 1)
            if type(n) is not int or n != 1:
                raise BusinessRuleError("Budgeted completions require a single choice")
            try:
                budget_usd = Decimal(str(definition.budget_limit))
                if not budget_usd.is_finite() or budget_usd < 0 or budget_usd > 1_000_000:
                    raise ValueError("Invalid budget")
                limit = int((budget_usd * 1_000_000).to_integral_value(rounding=ROUND_FLOOR))
            except (ValueError, InvalidOperation):
                raise BusinessRuleError("Agent budget configuration invalid") from None

            try:
                rate_in = Decimal(str(profile.cost_per_1k_input))
                rate_out = Decimal(str(profile.cost_per_1k_output))
                if (not rate_in.is_finite() or not rate_out.is_finite()
                        or rate_in < 0 or rate_out < 0):
                    raise ValueError("Invalid model pricing")
            except (InvalidOperation, ValueError):
                raise BusinessRuleError("Budget pricing configuration unavailable") from None
            input_cap = profile.context_window
            if (rate_in > 0 and (type(input_cap) is not int or not 1 <= input_cap <= 1_000_000)
                    or rate_out > 0 and (type(max_tokens) is not int or not 1 <= max_tokens <= 1_000_000)):
                raise BusinessRuleError("Budget requires bounded context_window and max_tokens")
            # Do not trust a database context_window as proof that the
            # submitted prompt fits it: account for UTF-8 message bytes,
            # role metadata and a conservative per-message framing margin.
            if rate_in > 0 and self._prompt_upper_bound(messages) > input_cap:
                raise BusinessRuleError("Agent prompt exceeds budgeted context_window")
            reserve = self._microusd(
                profile,
                input_cap if type(input_cap) is int and input_cap > 0 else 0,
                max_tokens if type(max_tokens) is int and max_tokens > 0 else 0,
            )
            spent_usd = (
                await session.execute(
                    select(func.coalesce(func.sum(TokenUsage.est_cost), 0.0))
                    .select_from(TokenUsage)
                    .join(AgentInstance, AgentInstance.id == TokenUsage.agent_instance_id)
                    .where(AgentInstance.agent_definition_id == definition.id)
                )
            ).scalar_one()
            try:
                spent = int((Decimal(str(spent_usd)) * 1_000_000).to_integral_value(rounding=ROUND_CEILING))
            except (ValueError, InvalidOperation):
                raise BusinessRuleError("Budget usage accounting invalid") from None
            held = (
                await session.execute(
                    select(func.coalesce(func.sum(AgentBudgetReservation.reserved_microusd), 0))
                    .where(AgentBudgetReservation.agent_definition_id == definition.id)
                )
            ).scalar_one()
            if spent < 0 or held < 0 or spent + held + reserve > limit:
                raise BusinessRuleError("Agent profile estimated budget exhausted")
            row = AgentBudgetReservation(
                agent_definition_id=definition.id, reserved_microusd=reserve,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row.id

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
            if instance.status != "running":
                raise StateTransitionError(
                    f"Agent instance must be running to complete; status={instance.status}"
                )
            # An instance is bound to its selected model by the control plane.
            # The HTTP caller must not switch models or silently fall back to
            # a provider-wide default after the instance has been created.
            if not instance.model_profile_id:
                raise BusinessRuleError("Agent instance requires an assigned model profile")
            if model_profile_id is not None and model_profile_id != instance.model_profile_id:
                raise ValidationError("Model profile override conflicts with agent instance binding")
            model_profile_id = instance.model_profile_id
            async with self.sf() as session:
                binding = await session.get(AgentExecutionBinding, instance.id)
            if binding is None:
                raise BusinessRuleError("Agent instance has no trusted revision binding; recreate instance")
            definition = await self.agent_definitions.get(instance.agent_definition_id)
            if definition.version != binding.definition_version:
                raise BusinessRuleError("Agent definition changed; recreate instance")
            if instance.tool_policy_id:
                policy = await self.tool_policies.get(instance.tool_policy_id)
                if policy.version != binding.policy_version:
                    raise BusinessRuleError("Tool policy changed; recreate instance")
                _require_qa_safe_policy(definition.role, policy)
            elif binding.policy_version is not None:
                raise BusinessRuleError("Tool policy binding invalid; recreate instance")
        provider = await self.providers.get_provider(provider_id)
        if not provider.is_active:
            raise BusinessRuleError(f"Provider '{provider.name}' is inactive")

        profile = None
        if model_profile_id:
            profile = await self.model_profiles.get(model_profile_id)
            if profile.provider_id != provider.id:
                raise ValidationError("model_profile does not belong to the given provider")
        else:
            profile = await self.model_profiles.resolve_default(provider.id)

        if agent_instance_id:
            # Check all relevant revisions before the provider is constructed.
            # The running instance keeps its selected identities; editing a
            # profile must never silently change a later completion.
            if (profile is None
                    or profile.version != binding.model_version
                    or provider.id != binding.provider_id
                    or provider.version != binding.provider_version):
                raise BusinessRuleError("Agent model/provider changed; recreate instance")

        model = profile.model_id if profile else None
        # Model-profile parameters are defaults, explicit completion arguments
        # always override them. They are controlled by the backend profile,
        # never injected by an untrusted tool-call payload.
        configured = profile.parameters or {} if profile else {}
        if agent_instance_id:
            # A profile-bound instance must not receive per-request inference
            # overrides that alter its operator-selected model parameters.
            # Unbound introspection completions retain their existing API.
            if (
                temperature is not None
                and ("temperature" not in configured or temperature != configured["temperature"])
            ):
                raise ValidationError("Agent instance temperature override conflicts with assigned model profile")
            if (
                max_tokens is not None
                and ("max_tokens" not in configured or max_tokens != configured["max_tokens"])
            ):
                raise ValidationError("Agent instance max_tokens override conflicts with assigned model profile")
        if temperature is None:
            temperature = configured.get("temperature")
        if max_tokens is None:
            max_tokens = configured.get("max_tokens")
        if agent_instance_id:
            # AgentDefinition instructions are server-owned. Request messages
            # may provide user content and prior assistant replies, never a
            # replacement system/developer/tool authority. Do not trust extra
            # keys such as provider-specific role or tool metadata.
            if (not isinstance(messages, list) or not 1 <= len(messages) <= 64
                    or any(
                        type(m) is not dict or set(m) != {"role", "content"}
                        or m["role"] not in ("user", "assistant")
                        or type(m["content"]) is not str or len(m["content"]) > 32768
                        for m in messages
                    )):
                raise ValidationError("Agent instance accepts only bounded user/assistant messages")
            system_prompt = definition.system_prompt
            if system_prompt is not None:
                if not isinstance(system_prompt, str) or not system_prompt.strip() or len(system_prompt) > 4096:
                    raise BusinessRuleError("Agent definition has invalid trusted system instructions")
                messages = [{"role": "system", "content": system_prompt}, *messages]
        budget_reservation_id = None
        if agent_instance_id:
            budget_reservation_id = await self._reserve_estimated_budget(
                instance=instance, binding=binding, profile=profile, max_tokens=max_tokens,
                messages=messages, provider=provider,
            )
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

        if budget_reservation_id is not None and result.metadata.get("usage_reported") is not True:
            # The HTTP fallback estimates token usage from text length and may
            # return zero for a genuinely billed request. Never release a
            # prepaid reservation without trustworthy provider usage.
            from .errors import TokenUsageError

            raise TokenUsageError("Provider usage unavailable; budget reservation requires reconciliation")
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
                budget_reservation_id=budget_reservation_id,
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
        # Never round positive usage to zero: the budget ledger sums these
        # persisted cost estimates across all instances. Rounding down would
        # allow unlimited sub-microdollar completions through the same cap.
        try:
            amount = (
                Decimal(str(profile.cost_per_1k_input)) * prompt_tokens
                + Decimal(str(profile.cost_per_1k_output)) * completion_tokens
            ) / Decimal(1000)
            if not amount.is_finite() or amount < 0:
                raise ValueError("Invalid cost")
            return float(amount.quantize(Decimal("0.000001"), rounding=ROUND_CEILING))
        except (InvalidOperation, ValueError, OverflowError):
            raise BusinessRuleError("Provider usage or model pricing invalid") from None