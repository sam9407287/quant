"""Unit tests for Google token verification and role mapping (ADR-005)."""

from __future__ import annotations

import pytest

from app.auth import google as google_mod
from app.auth.dependency import role_for
from app.auth.google import AuthError, verify_google_token


def _patch_verify(monkeypatch: pytest.MonkeyPatch, result: object) -> None:
    def fake(token: str, transport: object, client_id: str) -> dict:
        if isinstance(result, Exception):
            raise result
        assert isinstance(result, dict)
        return result

    monkeypatch.setattr(google_mod.id_token, "verify_oauth2_token", fake)


VALID = {
    "iss": "https://accounts.google.com",
    "sub": "1234567890",
    "email": "friend@example.com",
    "name": "Friend",
    "picture": "https://example.com/p.png",
}


class TestVerifyGoogleToken:
    def test_valid_token_maps_claims(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_verify(monkeypatch, VALID)
        claims = verify_google_token("tok", "client-id")
        assert claims.sub == "1234567890"
        assert claims.email == "friend@example.com"
        assert claims.name == "Friend"

    def test_google_rejection_becomes_auth_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # google-auth signals bad signature/audience/expiry via ValueError.
        _patch_verify(monkeypatch, ValueError("Token expired"))
        with pytest.raises(AuthError, match="Token expired"):
            verify_google_token("tok", "client-id")

    def test_non_google_issuer_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_verify(monkeypatch, {**VALID, "iss": "https://evil.example"})
        with pytest.raises(AuthError, match="issuer"):
            verify_google_token("tok", "client-id")

    def test_missing_email_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_verify(monkeypatch, {"iss": "accounts.google.com", "sub": "1"})
        with pytest.raises(AuthError, match="email"):
            verify_google_token("tok", "client-id")


class TestRoleMapping:
    def test_allowlisted_email_is_admin_case_insensitive(self) -> None:
        assert role_for("Sam9407287@Gmail.com", ["sam9407287@gmail.com"]) == "admin"

    def test_other_emails_are_users(self) -> None:
        assert role_for("friend@example.com", ["sam9407287@gmail.com"]) == "user"

    def test_empty_allowlist(self) -> None:
        assert role_for("sam9407287@gmail.com", []) == "user"
