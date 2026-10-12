"""End-to-end tests of the agent-management service layer: provider/model-profile/
tool-policy/agent-definition CRUD, agent-instance lifecycle state machine, and
optimistic locking + duplicate/not-found error mapping.
"""

from __future__ import annotations

import pytest

from agent_management.errors import (
    DuplicateKeyError,
    NotFoundError,
    OptimisticLockError,
    StateTransitionError,
    ValidationError,
)
from tests.conftest import (
    seed_definition,
    seed_policy,
    seed_profile,
    seed_provider,
)


class TestProviderCRUD:
    async def test_create_and_get(self, harness):
        p = await seed_provider(harness, name="p1", type="mock")
        assert p.name == "p1"
        got = await harness.service.providers.get_provider(p.id)
        assert got.id == p.id
        assert got.type == "mock"

    async def test_duplicate_name_rejected(self, harness):
        await seed_provider(harness, name="dup", type="mock")
        with pytest.raises(DuplicateKeyError):
            await seed_provider(harness, name="dup", type="mock")

    async def test_unknown_type_rejected(self, harness):
        with pytest.raises(ValidationError):
            await harness.service.providers.create_provider(
                {"name": "x", "type": "bogus"}
            )

    async def test_update_and_optimistic_lock(self, harness):
        p = await seed_provider(harness, name="up", type="mock")
        updated = await harness.service.providers.update_provider(
            p.id, {"is_active": False, "version": p.version}
        )
        assert updated.is_active is False
        with pytest.raises(OptimisticLockError):
            await harness.service.providers.update_provider(
                p.id, {"is_active": True, "version": p.version}
            )

    async def test_delete_and_get_missing(self, harness):
        p = await seed_provider(harness, name="gone", type="mock")
        await harness.service.providers.delete_provider(p.id)
        with pytest.raises(NotFoundError):
            await harness.service.providers.get_provider(p.id)

    async def test_list_providers(self, harness):
        for i in range(3):
            await seed_provider(harness, name=f"pl{i}", type="mock")
        rows, total, next_cursor = await harness.service.providers.list_providers()
        assert total == 3
        assert {r.name for r in rows} == {"pl0", "pl1", "pl2"}
        assert next_cursor is None


class TestModelProfileCRUD:
    async def test_create_bound_to_provider(self, harness):
        p = await seed_provider(harness, name="mp-provider")
        mp = await seed_profile(harness, p.id, name="pro", model_id="m1")
        assert mp.provider_id == p.id
        assert mp.is_default is True

    async def test_default_singleton_per_provider(self, harness):
        p = await seed_provider(harness, name="mp-provider2")
        await seed_profile(harness, p.id, name="a", model_id="m1", is_default=True)
        await seed_profile(harness, p.id, name="b", model_id="m2", is_default=True)
        profiles, _, _ = await harness.service.model_profiles.list(provider_id=p.id)
        defaults = [mp for mp in profiles if mp.is_default]
        assert len(defaults) == 1 and defaults[0].name == "b"

    async def test_profile_for_missing_provider_fails(self, harness):
        with pytest.raises(NotFoundError):
            await harness.service.model_profiles.create(
                {"provider_id": "does-not-exist", "name": "x", "model_id": "m"}
            )

    async def test_delete_profile(self, harness):
        p = await seed_provider(harness, name="mp-provider3")
        mp = await seed_profile(harness, p.id)
        await harness.service.model_profiles.delete(mp.id)
        with pytest.raises(NotFoundError):
            await harness.service.model_profiles.get(mp.id)