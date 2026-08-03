"""Strategy sharing between accounts.

A `strategy_access` row is one direction of a pair: `grantee_id` asking to
read `owner_id`'s strategies. Access is read-plus-copy — a grantee can list,
open and evaluate the owner's strategies, and copy one into their own
account, but never edit or delete the owner's row. That asymmetry lives in
`app/api/strategies.py`, which passes the widened owner set to reads only.

Pure-SQL access via SQLAlchemy `text()`, matching the sibling repositories.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def find_user_by_email(session: AsyncSession, email: str) -> dict[str, Any] | None:
    """Look up a user by email, case-insensitively.

    Returns None when the address has never signed in — sharing cannot be
    offered to an account the system has never seen.
    """
    row = (
        await session.execute(
            text(
                "SELECT id::text AS id, email, name FROM users "
                "WHERE lower(email) = lower(:email) LIMIT 1"
            ),
            {"email": email.strip()},
        )
    ).mappings().first()
    return dict(row) if row else None


async def granted_owner_ids(session: AsyncSession, grantee_id: str) -> list[str]:
    """Owner ids whose strategies `grantee_id` may currently read.

    Tolerates the table not existing yet. This query runs on every strategy
    listing, so if the API is deployed before
    `db/migrations/001_strategy_access.sql` has been applied, an unguarded
    failure would take the whole strategies page down. Degrading to "no
    sharing" keeps the deploy order from mattering.
    """
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT owner_id::text AS id FROM strategy_access "
                    "WHERE grantee_id = CAST(:me AS UUID) AND status = 'granted'"
                ),
                {"me": grantee_id},
            )
        ).scalars().all()
    except ProgrammingError:
        logger.warning(
            "strategy_access is missing — sharing is inactive until the "
            "migration is applied"
        )
        await session.rollback()
        return []
    return [str(r) for r in rows]


async def request_access(
    session: AsyncSession, *, owner_id: str, grantee_id: str, message: str | None
) -> dict[str, Any]:
    """Create or revive a request.

    Re-requesting after a denial or revocation reuses the same row and puts
    it back to pending — the unique (owner, grantee) pair is what makes the
    upsert safe against a double click.
    """
    row = (
        await session.execute(
            text(
                """
                INSERT INTO strategy_access (owner_id, grantee_id, status, message)
                VALUES (CAST(:owner AS UUID), CAST(:grantee AS UUID), 'pending', :message)
                ON CONFLICT (owner_id, grantee_id) DO UPDATE
                SET status = CASE
                        WHEN strategy_access.status = 'granted' THEN 'granted'
                        ELSE 'pending'
                    END,
                    message = EXCLUDED.message,
                    requested_at = NOW(),
                    decided_at = NULL,
                    seen_at = NULL
                RETURNING id::text AS id, status, requested_at
                """
            ),
            {"owner": owner_id, "grantee": grantee_id, "message": message},
        )
    ).mappings().one()
    await session.commit()
    return dict(row)


async def decide(
    session: AsyncSession, *, request_id: str, owner_id: str, status: str
) -> bool:
    """Approve, deny or revoke. Scoped to the owner so nobody decides for others."""
    result = await session.execute(
        text(
            """
            UPDATE strategy_access
            SET status = :status, decided_at = NOW(), seen_at = COALESCE(seen_at, NOW())
            WHERE id = CAST(:id AS UUID) AND owner_id = CAST(:owner AS UUID)
            """
        ),
        {"id": request_id, "owner": owner_id, "status": status},
    )
    await session.commit()
    return result.rowcount > 0


async def mark_seen(session: AsyncSession, owner_id: str) -> None:
    """Clear the pending badge without deciding the requests themselves."""
    await session.execute(
        text(
            "UPDATE strategy_access SET seen_at = NOW() "
            "WHERE owner_id = CAST(:owner AS UUID) AND status = 'pending' AND seen_at IS NULL"
        ),
        {"owner": owner_id},
    )
    await session.commit()


async def list_incoming(session: AsyncSession, owner_id: str) -> list[dict[str, Any]]:
    """Requests other people have made to read my strategies."""
    rows = (
        await session.execute(
            text(
                """
                SELECT a.id::text AS id, a.status, a.message, a.requested_at,
                       a.decided_at, a.seen_at,
                       u.email AS counterparty_email, u.name AS counterparty_name,
                       u.picture AS counterparty_picture
                FROM strategy_access a
                JOIN users u ON u.id = a.grantee_id
                WHERE a.owner_id = CAST(:me AS UUID)
                ORDER BY (a.status = 'pending') DESC, a.requested_at DESC
                """
            ),
            {"me": owner_id},
        )
    ).mappings().all()
    return [dict(r) for r in rows]


async def list_outgoing(session: AsyncSession, grantee_id: str) -> list[dict[str, Any]]:
    """Requests I have made to read other people's strategies."""
    rows = (
        await session.execute(
            text(
                """
                SELECT a.id::text AS id, a.status, a.message, a.requested_at,
                       a.decided_at, a.seen_at,
                       u.email AS counterparty_email, u.name AS counterparty_name,
                       u.picture AS counterparty_picture
                FROM strategy_access a
                JOIN users u ON u.id = a.owner_id
                WHERE a.grantee_id = CAST(:me AS UUID)
                ORDER BY a.requested_at DESC
                """
            ),
            {"me": grantee_id},
        )
    ).mappings().all()
    return [dict(r) for r in rows]


async def pending_count(session: AsyncSession, owner_id: str) -> int:
    """Unseen incoming requests — what the nav badge counts."""
    return int(
        (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM strategy_access "
                    "WHERE owner_id = CAST(:me AS UUID) AND status = 'pending' "
                    "AND seen_at IS NULL"
                ),
                {"me": owner_id},
            )
        ).scalar_one()
    )
