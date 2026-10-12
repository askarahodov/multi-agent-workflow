"""Service layer for the orchestration server.

Each service owns a slice of domain logic that is intentionally kept out of the
API routing layer, so the behaviour can be exercised and tested independently of
HTTP. Services depend only on the async session factory and the domain models.
"""