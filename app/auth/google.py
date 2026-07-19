"""Google ID-token verification.

The frontend obtains an ID token from Google Identity Services and
sends it as `Authorization: Bearer <token>`. Verification happens
locally against Google's published signing keys (google-auth caches
them), so no per-request network round-trip in the steady state.
"""

from __future__ import annotations

from dataclasses import dataclass

from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

# Module-level transport: reuses the underlying HTTP session so
# Google's certificates are fetched once and then served from cache.
_transport = google_requests.Request()

_GOOGLE_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}


class AuthError(Exception):
    """Raised when a bearer token cannot be verified."""


@dataclass(frozen=True, slots=True)
class GoogleClaims:
    """The subset of ID-token claims the app cares about."""

    sub: str
    email: str
    name: str | None
    picture: str | None


def verify_google_token(token: str, client_id: str) -> GoogleClaims:
    """Verify signature/audience/expiry and return the identity claims."""
    try:
        info = id_token.verify_oauth2_token(token, _transport, client_id)
    except Exception as exc:  # google-auth raises bare ValueError et al.
        raise AuthError(f"invalid Google ID token: {exc}") from exc
    if info.get("iss") not in _GOOGLE_ISSUERS:
        raise AuthError("token issuer is not Google")
    email = info.get("email")
    if not email:
        raise AuthError("token carries no email claim")
    return GoogleClaims(
        sub=str(info["sub"]),
        email=str(email),
        name=info.get("name"),
        picture=info.get("picture"),
    )
