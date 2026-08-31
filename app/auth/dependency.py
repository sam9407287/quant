"""FastAPI dependency resolving the bearer token to a local user row.

Sits alongside `app.db.session.get_db` in route signatures:

    user: CurrentUser = Depends(get_current_user)

The users row is upserted on every request (cheap single statement) so
name/picture stay fresh and the admin role tracks the ADMIN_EMAILS
allowlist without a management UI. Integration tests override this
dependency instead of minting real Google tokens.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.google import AuthError, GoogleClaims, verify_google_token
from app.core.config import get_settings
from app.db.session import get_db


@dataclass(frozen=True, slots=True)
class CurrentUser:
    """The authenticated caller, as stored in the users table."""

    id: str
    email: str
    role: str  # 'user' | 'admin'
    name: str | None = None
    picture: str | None = None

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def owner_filter(self) -> str | None:
        """Owner id to filter queries by — None means see everything."""
        return None if self.is_admin else self.id


def role_for(email: str, admin_emails: list[str]) -> str:
    """Allowlist check, case-insensitive on both sides."""
    return "admin" if email.lower() in {e.lower() for e in admin_emails} else "user"


async def _upsert_user(
    db: AsyncSession, claims: GoogleClaims, role: str
) -> CurrentUser:
    stmt = text(
        """
        INSERT INTO users (google_sub, email, name, picture, role)
        VALUES (:sub, :email, :name, :picture, :role)
        ON CONFLICT (google_sub) DO UPDATE
        SET email = :email, name = :name, picture = :picture, role = :role
        RETURNING id::text, email, role, name, picture
        """
    )
    row = (
        await db.execute(
            stmt,
            {
                "sub": claims.sub,
                "email": claims.email,
                "name": claims.name,
                "picture": claims.picture,
                "role": role,
            },
        )
    ).one()
    await db.commit()
    return CurrentUser(id=row.id, email=row.email, role=row.role, name=row.name, picture=row.picture)


# A secret shorter than this is refused even when configured: the whole
# safety of the service token is that it cannot be guessed, and a
# placeholder like "test" left in an env var would be a back door.
_MIN_SERVICE_TOKEN_LEN = 32


def service_token_matches(token: str, configured: str) -> bool:
    """Constant-time check of the presented token against the configured one."""
    if not configured or len(configured) < _MIN_SERVICE_TOKEN_LEN:
        return False
    return secrets.compare_digest(token, configured)


async def _upsert_service_user(db: AsyncSession, email: str, role: str) -> CurrentUser:
    """The account the service token authenticates as.

    Its own row, keyed by a synthetic `google_sub` no Google account can
    collide with, so its strategies and runs are separable from a real
    user's and it can be deleted on its own.
    """
    claims = GoogleClaims(sub=f"service-token:{email}", email=email, name="service token", picture=None)
    return await _upsert_user(db, claims, role)


async def get_current_user(
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> CurrentUser:
    """Resolve the request's bearer token to a CurrentUser or 401/503."""
    settings = get_settings()
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = authorization.removeprefix("Bearer ").strip()

    # Checked before the Google path so an automated client works against a
    # server with no OAuth client configured at all (a local backend, say).
    if service_token_matches(token, settings.service_token):
        return await _upsert_service_user(
            db,
            settings.service_token_email,
            role_for(settings.service_token_email, settings.admin_emails),
        )

    if not settings.google_oauth_client_id:
        raise HTTPException(
            status_code=503,
            detail="sign-in is not configured on this server (GOOGLE_OAUTH_CLIENT_ID unset)",
        )
    try:
        claims = verify_google_token(token, settings.google_oauth_client_id)
    except AuthError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e
    return await _upsert_user(db, claims, role_for(claims.email, settings.admin_emails))
