"""Sharing strategies between Google accounts.

The grantee asks by email address; the owner approves. Access is
read-plus-copy — see `app/strategies/access.py` for why writes stay
owner-only.

Emails are best-effort: a provider outage must not fail the request, so
delivery failures are logged and the in-app notification carries on.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependency import CurrentUser, get_current_user
from app.db.session import get_db
from app.notify.email import send_access_decided, send_access_requested
from app.strategies.access import (
    decide,
    find_user_by_email,
    list_incoming,
    list_outgoing,
    mark_seen,
    pending_count,
    request_access,
)

router = APIRouter(prefix="/api/v1/strategy-access", tags=["strategy-access"])


class AccessRequestIn(BaseModel):
    email: str = Field(
        max_length=254, description="Google account whose strategies you want to read"
    )
    message: str | None = Field(default=None, max_length=280)

    @field_validator("email")
    @classmethod
    def looks_like_an_address(cls, v: str) -> str:
        """Shape check only. The real gate is that the address must already
        exist in `users`, so full RFC validation would buy nothing but a
        dependency."""
        candidate = v.strip()
        local, _, domain = candidate.partition("@")
        if not local or "." not in domain or domain.startswith(".") or domain.endswith("."):
            raise ValueError("not an email address")
        return candidate


class AccessRow(BaseModel):
    id: str
    status: str
    message: str | None = None
    requested_at: datetime
    decided_at: datetime | None = None
    seen_at: datetime | None = None
    counterparty_email: str
    counterparty_name: str | None = None
    counterparty_picture: str | None = None


class AccessOverview(BaseModel):
    incoming: list[AccessRow]
    outgoing: list[AccessRow]
    pending_count: int


@router.get("", response_model=AccessOverview, summary="Sharing state for the caller")
async def overview(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> AccessOverview:
    return AccessOverview(
        incoming=[AccessRow(**r) for r in await list_incoming(db, user.id)],
        outgoing=[AccessRow(**r) for r in await list_outgoing(db, user.id)],
        pending_count=await pending_count(db, user.id),
    )


@router.post("/requests", response_model=AccessRow, summary="Ask to read someone's strategies")
async def create_request(
    payload: AccessRequestIn,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> AccessRow:
    owner = await find_user_by_email(db, payload.email)
    if owner is None:
        # Deliberately explicit: sharing can only target an account that has
        # signed in at least once, and saying so is more useful than a 404.
        raise HTTPException(
            404,
            f"No account has signed in with {payload.email}. "
            "Ask them to sign in once, then request again.",
        )
    if owner["id"] == user.id:
        raise HTTPException(400, "You already have access to your own strategies.")

    await request_access(
        db, owner_id=owner["id"], grantee_id=user.id, message=payload.message
    )
    send_access_requested(
        to=owner["email"], requester_email=user.email, message=payload.message
    )

    rows = await list_outgoing(db, user.id)
    row = next(r for r in rows if r["counterparty_email"].lower() == owner["email"].lower())
    return AccessRow(**row)


class DecisionIn(BaseModel):
    status: str = Field(pattern="^(granted|denied|revoked)$")


@router.post("/requests/{request_id}/decide", summary="Approve, deny or revoke")
async def decide_request(
    request_id: str,
    payload: DecisionIn,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, str]:
    if not await decide(db, request_id=request_id, owner_id=user.id, status=payload.status):
        raise HTTPException(404, "No such request, or it is not yours to decide.")

    row = next((r for r in await list_incoming(db, user.id) if r["id"] == request_id), None)
    if row is not None and payload.status in ("granted", "denied"):
        send_access_decided(
            to=row["counterparty_email"],
            owner_email=user.email,
            granted=payload.status == "granted",
        )
    return {"status": payload.status}


@router.post("/seen", summary="Clear the pending-request badge")
async def mark_requests_seen(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, int]:
    await mark_seen(db, user.id)
    return {"pending_count": 0}
