"""One-off maintenance commands runnable inside the api container.

Invoked via `railway ssh --service quant -- python -m app.admin_tasks
<command>` — single-word arguments only, because railway ssh does not
preserve shell quoting. Ships in the image (Dockerfile copies app/), so
no separate tooling is needed on the box.
"""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy import text

from app.db.session import AsyncSessionLocal


async def adopt_legacy(email: str) -> None:
    """Assign ownerless strategies/backtest runs to the user with `email`.

    Legacy rows predate ADR-005 (created before auth existed). The
    target user must have signed in at least once so their users row
    exists.
    """
    async with AsyncSessionLocal() as db:
        row = (
            await db.execute(
                text("SELECT id::text, role FROM users WHERE email = :e"),
                {"e": email},
            )
        ).fetchone()
        if row is None:
            print(f"ERROR: no users row for {email} — sign in once first")
            sys.exit(1)
        user_id = row[0]
        for table in ("strategies", "backtest_runs"):
            result = await db.execute(
                text(
                    f"UPDATE {table} SET owner_id = CAST(:uid AS UUID) "  # noqa: S608
                    "WHERE owner_id IS NULL"
                ),
                {"uid": user_id},
            )
            print(f"{table}: adopted {result.rowcount} rows")  # type: ignore[attr-defined]
        await db.commit()
    print(f"done — legacy rows now belong to {email} ({row[1]})")


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: python -m app.admin_tasks adopt_legacy [email]")
        sys.exit(2)
    command = sys.argv[1]
    if command == "adopt_legacy":
        email = sys.argv[2] if len(sys.argv) > 2 else "sam9407287@gmail.com"
        asyncio.run(adopt_legacy(email))
    else:
        print(f"unknown command: {command}")
        sys.exit(2)


if __name__ == "__main__":
    main()
