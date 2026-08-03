"""Unit coverage for the strategy-sharing pieces that need no database.

The SQL paths are Postgres-specific (UUID casts, string_to_array) and are
exercised by the integration suite; what is checked here is the logic that
decides *who sees what* and the email fallback, both of which are pure.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.api.strategy_access import AccessRequestIn, DecisionIn
from app.notify.email import _send
from app.strategies.repository import _owners_param


class TestOwnersParam:
    """The read filter must fail closed."""

    def test_admin_sees_everything(self) -> None:
        # None means "no owner condition" — reserved for admins.
        assert _owners_param(None) is None

    def test_single_owner(self) -> None:
        assert _owners_param(["abc"]) == "abc"

    def test_own_plus_granted(self) -> None:
        assert _owners_param(["me", "them"]) == "me,them"

    def test_empty_list_matches_nothing(self) -> None:
        """An empty set must not collapse into None and expose every row."""
        result = _owners_param([])
        assert result is not None
        assert result == "00000000-0000-0000-0000-000000000000"


class TestAccessRequestValidation:
    @pytest.mark.parametrize(
        "address",
        ["a@b.co", "first.last@gmail.com", "  spaced@example.com  "],
    )
    def test_accepts_plausible_addresses(self, address: str) -> None:
        assert "@" in AccessRequestIn(email=address).email

    def test_trims_whitespace(self) -> None:
        assert AccessRequestIn(email="  x@y.com ").email == "x@y.com"

    @pytest.mark.parametrize(
        "address",
        ["", "no-at-sign", "@nolocal.com", "missing@domain", "trailing@dot."],
    )
    def test_rejects_malformed(self, address: str) -> None:
        with pytest.raises(ValidationError):
            AccessRequestIn(email=address)

    def test_message_is_bounded(self) -> None:
        with pytest.raises(ValidationError):
            AccessRequestIn(email="a@b.co", message="x" * 281)


class TestDecisionValidation:
    @pytest.mark.parametrize("status", ["granted", "denied", "revoked"])
    def test_allows_the_three_outcomes(self, status: str) -> None:
        assert DecisionIn(status=status).status == status

    @pytest.mark.parametrize("status", ["pending", "approved", "", "DELETE"])
    def test_rejects_anything_else(self, status: str) -> None:
        """'pending' is the initial state, not something an owner can decide."""
        with pytest.raises(ValidationError):
            DecisionIn(status=status)


class TestEmailFallback:
    def test_unconfigured_provider_is_a_no_op(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No key must skip the send, not raise — the in-app path carries on."""
        import app.notify.email as mail

        def boom(*_args: object, **_kwargs: object) -> None:  # pragma: no cover
            raise AssertionError("must not reach the network without a key")

        monkeypatch.setattr(mail.requests, "post", boom)
        assert _send("someone@example.com", "subject", "<p>body</p>") is False

    def test_provider_error_is_swallowed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A notification must never take the API request down with it."""
        import app.notify.email as mail

        settings = mail.get_settings()
        monkeypatch.setattr(settings, "resend_api_key", "key", raising=False)
        monkeypatch.setattr(settings, "notify_from_email", "a@b.co", raising=False)

        def raise_network(*_args: object, **_kwargs: object) -> None:
            raise mail.requests.RequestException("down")

        monkeypatch.setattr(mail.requests, "post", raise_network)
        assert _send("someone@example.com", "subject", "<p>body</p>") is False
