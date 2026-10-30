"""WorkflowDefinition / WorkflowVersion CRUD service (design-time domain).

Owns all persistence for the workflow-definition domain (ADR-102: the
orchestration server is the source of truth for definitions and versions). The
service keeps the API layer thin and lets the behaviour be tested independently
of HTTP.

Pagination is cursor-based (ADR-101) via :mod:`services.cursor`: pages are
ordered by ``(created_at DESC, id DESC)`` and ``next_cursor`` encodes the last
row, so the client can request the following page with ``?after=...``.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from ..errors import (
    ConflictError,
    DuplicateKeyError,
    NotFoundError,
    ValidationError,
)
from ..models import WorkflowDefinition, WorkflowVersion
from .cursor import apply_keyset_predicate, fetch_one_more, split_page


class WorkflowService:
    """Persistence operations for workflow definitions and their versions."""

    def __init__(self, session_factory: async_sessionmaker) -> None:
        self._sf = session_factory

    @staticmethod
    def _key_of_definition(row: WorkflowDefinition):
        return (row.created_at, row.id)

    @staticmethod
    def _key_of_version(row: WorkflowVersion):
        return (row.created_at, row.id)

    async def list_definitions(
        self, after: Optional[str] = None, limit: int = 50
    ) -> tuple[list[WorkflowDefinition], Optional[str]]:
        async with self._sf() as session:
            stmt = select(WorkflowDefinition)
            stmt = apply_keyset_predicate(
                stmt, WorkflowDefinition.created_at, WorkflowDefinition.id, after
            )
            stmt = stmt.order_by(
                WorkflowDefinition.created_at.desc(), WorkflowDefinition.id.desc()
            )
            stmt = fetch_one_more(stmt, limit)
            rows = list((await session.scalars(stmt)).all())
            page, next_cursor = split_page(rows, limit, self._key_of_definition)
            # Detach so attribute access after session close is safe.
            for r in page:
                session.expunge(r)
            return page, next_cursor

    async def get_definition(self, definition_id: str) -> WorkflowDefinition:
        async with self._sf() as session:
            obj = await session.get(WorkflowDefinition, definition_id)
            if obj is None:
                raise NotFoundError(f"Workflow definition {definition_id} not found")
            return obj

    async def create_definition(
        self,
        name: str,
        definition: dict,
        description: Optional[str] = None,
    ) -> WorkflowDefinition:
        if not isinstance(definition, dict):
            raise ValidationError("Workflow 'definition' must be a JSON object")
        async with self._sf() as session:
            existing = await session.scalar(
                select(WorkflowDefinition.id).where(WorkflowDefinition.name == name)
            )
            if existing is not None:
                raise DuplicateKeyError(f"A workflow definition named '{name}' already exists")
            obj = WorkflowDefinition(
                name=name,
                description=description,
                definition=definition,
                is_active=True,
                version=1,
            )
            session.add(obj)
            await session.commit()
            await session.refresh(obj)
            return obj

    async def update_definition(
        self,
        definition_id: str,
        *,
        name: Optional[str] = None,
        description: Optional[str] = None,
        definition: Optional[dict] = None,
        is_active: Optional[bool] = None,
    ) -> WorkflowDefinition:
        async with self._sf() as session:
            obj = await session.get(WorkflowDefinition, definition_id)
            if obj is None:
                raise NotFoundError(f"Workflow definition {definition_id} not found")
            if name is not None and name != obj.name:
                clash = await session.scalar(
                    select(WorkflowDefinition.id).where(
                        WorkflowDefinition.name == name,
                        WorkflowDefinition.id != definition_id,
                    )
                )
                if clash is not None:
                    raise DuplicateKeyError(f"A workflow definition named '{name}' already exists")
                obj.name = name
            if description is not None:
                obj.description = description
            if definition is not None:
                if not isinstance(definition, dict):
                    raise ValidationError("Workflow 'definition' must be a JSON object")
                obj.definition = definition
            if is_active is not None:
                obj.is_active = is_active
            obj.version = obj.version + 1
            await session.commit()
            await session.refresh(obj)
            return obj

    async def list_versions(
        self, definition_id: str, after: Optional[str] = None, limit: int = 50
    ) -> tuple[list[WorkflowVersion], Optional[str]]:
        async with self._sf() as session:
            exists = await session.get(WorkflowDefinition, definition_id)
            if exists is None:
                raise NotFoundError(f"Workflow definition {definition_id} not found")
            stmt = select(WorkflowVersion).where(
                WorkflowVersion.workflow_definition_id == definition_id
            )
            stmt = apply_keyset_predicate(
                stmt, WorkflowVersion.created_at, WorkflowVersion.id, after
            )
            stmt = stmt.order_by(
                WorkflowVersion.created_at.desc(), WorkflowVersion.id.desc()
            )
            stmt = fetch_one_more(stmt, limit)
            rows = list((await session.scalars(stmt)).all())
            page, next_cursor = split_page(rows, limit, self._key_of_version)
            for r in page:
                session.expunge(r)
            return page, next_cursor

    async def create_version(
        self,
        definition_id: str,
        definition_snapshot: dict,
        changelog: Optional[str] = None,
        created_by: Optional[str] = None,
    ) -> WorkflowVersion:
        if not isinstance(definition_snapshot, dict):
            raise ValidationError("'definition_snapshot' must be a JSON object")
        async with self._sf() as session:
            definition = await session.get(WorkflowDefinition, definition_id)
            if definition is None:
                raise NotFoundError(f"Workflow definition {definition_id} not found")
            next_number = await session.scalar(
                select(func.max(WorkflowVersion.version_number)).where(
                    WorkflowVersion.workflow_definition_id == definition_id
                )
            )
            version_number = (next_number or 0) + 1
            version = WorkflowVersion(
                workflow_definition_id=definition_id,
                version_number=version_number,
                definition_snapshot=definition_snapshot,
                changelog=changelog,
                created_by=created_by,
            )
            session.add(version)
            # The definition now points at this snapshot as its current version.
            definition.current_version_id = version.id
            definition.definition = definition_snapshot
            definition.version = definition.version + 1
            try:
                await session.commit()
            except Exception:  # pragma: no cover - defensive
                await session.rollback()
                raise ConflictError("Concurrent version creation conflict")
            await session.refresh(version)
            return version