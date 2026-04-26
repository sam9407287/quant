"""Unit tests for fetch result notifier."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fetcher.notifier import _build_payload, notify

SAMPLE_SUMMARY = {
    "NQ": {"fetched": 1380, "inserted": 200, "skipped": 1180},
    "ES": {"fetched": 1380, "inserted": 200, "skipped": 1180},
}


class TestBuildPayload:
    def test_success_has_green_color(self) -> None:
        payload = _build_payload(SAMPLE_SUMMARY, success=True, duration_seconds=12.3)
        assert payload["embeds"][0]["color"] == 0x2ECC71

    def test_failure_has_red_color(self) -> None:
        payload = _build_payload(SAMPLE_SUMMARY, success=False, duration_seconds=5.0)
        assert payload["embeds"][0]["color"] == 0xE74C3C

    def test_all_instruments_in_payload(self) -> None:
        payload = _build_payload(SAMPLE_SUMMARY, success=True, duration_seconds=10.0)
        content = payload["embeds"][0]["fields"][0]["value"]
        assert "NQ" in content
        assert "ES" in content

    def test_duration_field_present(self) -> None:
        payload = _build_payload(SAMPLE_SUMMARY, success=True, duration_seconds=42.5)
        fields = {f["name"]: f["value"] for f in payload["embeds"][0]["fields"]}
        assert "42.5s" in fields["Duration"]

    def test_empty_summary_does_not_raise(self) -> None:
        payload = _build_payload({}, success=True, duration_seconds=0.0)
        assert "embeds" in payload


class TestNotify:
    def test_skips_when_no_webhook_url(self) -> None:
        """No HTTP call should be made if NOTIFY_WEBHOOK_URL is empty."""
        with patch("fetcher.notifier.urllib.request.urlopen") as mock_open:
            notify(SAMPLE_SUMMARY)
        mock_open.assert_not_called()

    def test_sends_post_when_url_configured(self) -> None:
        with (
            patch("app.core.config.get_settings") as mock_settings,
            patch("fetcher.notifier.get_settings") as mock_notifier_settings,
            patch("fetcher.notifier.urllib.request.urlopen") as mock_open,
        ):
            cfg = MagicMock()
            cfg.notify_webhook_url = "https://hooks.example.com/test"
            mock_settings.return_value = cfg
            mock_notifier_settings.return_value = cfg

            mock_resp = MagicMock()
            mock_resp.status = 204
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_open.return_value = mock_resp

            notify(SAMPLE_SUMMARY, success=True, duration_seconds=5.0)

        mock_open.assert_called_once()

    def test_never_raises_on_network_error(self) -> None:
        """A failed webhook call must not propagate exceptions."""
        import urllib.error
        with (
            patch("fetcher.notifier.get_settings") as mock_settings,
            patch("fetcher.notifier.urllib.request.urlopen") as mock_open,
        ):
            cfg = MagicMock()
            cfg.notify_webhook_url = "https://hooks.example.com/fail"
            mock_settings.return_value = cfg
            mock_open.side_effect = urllib.error.URLError("timeout")

            # Must not raise
            notify(SAMPLE_SUMMARY, success=True, duration_seconds=1.0)
