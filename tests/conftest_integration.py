"""Shared fixtures for integration tests (require a real TimescaleDB instance).

Integration tests are skipped automatically when DATABASE_URL is missing
or doesn't look like a test database, so they never break CI without one.

To run locally:
    DATABASE_URL=postgresql+asyncpg://test:test@localhost:5433/quant_futures_test \
    pytest tests/ -m integration -v
"""

from __future__ import annotations

import contextlib
import os
import re

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


def _test_db_url() -> str | None:
    """Return DATABASE_URL if it looks like a test database, else None."""
    url = os.environ.get("DATABASE_URL", "")
    if any(marker in url for marker in ("test", "localhost", "127.0.0.1")):
        return url
    return None


@pytest.fixture(scope="session")
def test_db_url() -> str:
    url = _test_db_url()
    if not url:
        pytest.skip("Integration tests require DATABASE_URL pointing to a test database")
    return url


def _split_sql(raw: str) -> list[str]:
    """Split a multi-statement SQL string on bare semicolons, stripping comments."""
    cleaned = "\n".join(
        line for line in raw.splitlines() if not line.strip().startswith("--")
    )
    parts = re.split(r";\s*\n", cleaned)
    return [p.strip() for p in parts if p.strip()]


@pytest_asyncio.fixture(scope="function")
async def db_session(test_db_url: str) -> AsyncSession:
    """Provide a fresh async session for each integration test.

    Schema is applied idempotently with AUTOCOMMIT semantics so TimescaleDB
    helpers (compression policy, CA refresh policy) succeed.
    """
    engine = create_async_engine(test_db_url, echo=False)

    schema_path = os.path.join(os.path.dirname(__file__), "..", "db", "schema.sql")
    with open(schema_path) as f:
        schema_sql = f.read()

    async with engine.connect() as conn:
        await conn.execution_options(isolation_level="AUTOCOMMIT")
        for stmt in _split_sql(schema_sql):
            with contextlib.suppress(Exception):
                await conn.execute(text(stmt))

    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        yield session
        await session.rollback()

    await engine.dispose()
