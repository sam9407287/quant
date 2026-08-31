"""The service token: an automated client authenticating as its own account.

These exist to pin the properties that make it a key rather than a hole —
absent by default, unguessable, constant-time, and not an admin.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.auth.dependency import get_current_user, role_for, service_token_matches

GOOD = "f" * 64


class TestServiceTokenMatches:
    def test_unset_never_matches(self) -> None:
        # The default. Presenting an empty token must not authenticate.
        assert service_token_matches("", "") is False
        assert service_token_matches(GOOD, "") is False

    def test_a_short_secret_is_refused_even_when_configured(self) -> None:
        """A placeholder left in the env var must not become a back door."""
        assert service_token_matches("test", "test") is False
        assert service_token_matches("a" * 31, "a" * 31) is False
        assert service_token_matches("a" * 32, "a" * 32) is True

    def test_a_wrong_token_of_the_right_length_fails(self) -> None:
        assert service_token_matches("e" * 64, GOOD) is False

    def test_a_prefix_of_the_secret_fails(self) -> None:
        assert service_token_matches(GOOD[:40], GOOD) is False


class TestServiceTokenAuth:
    @pytest.fixture
    def db(self) -> AsyncMock:
        row = MagicMock(
            id="svc-1", email="service-bot@quant.local", role="user",
            name="service token", picture=None,
        )
        result = MagicMock()
        result.one.return_value = row
        db = AsyncMock()
        db.execute.return_value = result
        return db

    @pytest.mark.asyncio
    async def test_the_token_authenticates_without_google(
        self, db: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Works against a server with no OAuth client configured at all."""
        from app.auth import dependency as mod

        settings = MagicMock(
            service_token=GOOD,
            service_token_email="service-bot@quant.local",
            admin_emails=["sam9407287@gmail.com"],
            google_oauth_client_id="",
        )
        monkeypatch.setattr(mod, "get_settings", lambda: settings)

        user = await get_current_user(authorization=f"Bearer {GOOD}", db=db)
        assert user.email == "service-bot@quant.local"
        # Not an admin: a leaked secret buys a sandbox, not everyone's data.
        assert user.is_admin is False
        assert user.owner_filter == user.id

    @pytest.mark.asyncio
    async def test_without_the_env_var_the_path_does_not_exist(
        self, db: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.auth import dependency as mod

        settings = MagicMock(
            service_token="",
            service_token_email="service-bot@quant.local",
            admin_emails=[],
            google_oauth_client_id="",
        )
        monkeypatch.setattr(mod, "get_settings", lambda: settings)

        with pytest.raises(HTTPException) as exc:
            await get_current_user(authorization=f"Bearer {GOOD}", db=db)
        # Falls through to the Google path, which is unconfigured here.
        assert exc.value.status_code == 503

    @pytest.mark.asyncio
    async def test_no_bearer_is_still_401(
        self, db: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.auth import dependency as mod

        monkeypatch.setattr(
            mod, "get_settings",
            lambda: MagicMock(service_token=GOOD, google_oauth_client_id="x"),
        )
        with pytest.raises(HTTPException) as exc:
            await get_current_user(authorization=None, db=db)
        assert exc.value.status_code == 401

    def test_the_account_can_be_promoted_deliberately(self) -> None:
        """Adding its email to ADMIN_EMAILS is the only route to admin."""
        assert role_for("service-bot@quant.local", []) == "user"
        assert role_for("service-bot@quant.local", ["service-bot@quant.local"]) == "admin"
