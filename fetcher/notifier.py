"""Fetch result notification via webhook.

After each daily fetch, a structured JSON payload is sent to a configurable
webhook URL (e.g. Discord, Slack, or any HTTP endpoint). If no webhook is
configured, notifications are silently skipped.

Set NOTIFY_WEBHOOK_URL in environment variables to enable.
Discord example: https://discord.com/api/webhooks/...
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import urllib.request
import urllib.error
import json

from app.core.config import get_settings

logger = logging.getLogger(__name__)


def _build_payload(
    summary: dict[str, dict],
    success: bool,
    duration_seconds: float,
) -> dict:
    """Build the webhook JSON payload from a fetch summary."""
    lines = []
    total_inserted = 0
    total_fetched = 0

    for instrument, stats in summary.items():
        fetched  = stats.get("fetched", 0)
        inserted = stats.get("inserted", 0)
        skipped  = stats.get("skipped", 0)
        total_fetched  += fetched
        total_inserted += inserted
        lines.append(f"**{instrument}**: fetched={fetched} inserted={inserted} skipped={skipped}")

    status_emoji = "✅" if success else "❌"
    now_str = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    return {
        "content": None,
        "embeds": [
            {
                "title": f"{status_emoji} Daily Fetch — {now_str}",
                "color": 0x2ECC71 if success else 0xE74C3C,
                "fields": [
                    {
                        "name": "Instruments",
                        "value": "\n".join(lines) or "No data",
                        "inline": False,
                    },
                    {
                        "name": "Total inserted",
                        "value": str(total_inserted),
                        "inline": True,
                    },
                    {
                        "name": "Duration",
                        "value": f"{duration_seconds:.1f}s",
                        "inline": True,
                    },
                ],
            }
        ],
    }


def notify(
    summary: dict[str, dict],
    success: bool = True,
    duration_seconds: float = 0.0,
) -> None:
    """Send a fetch summary notification to the configured webhook.

    Silently skips if NOTIFY_WEBHOOK_URL is not set or is empty.
    Never raises — a failed notification must not affect the fetch pipeline.

    Args:
        summary:          Per-instrument fetch stats from run_daily_fetch().
        success:          Whether the overall fetch completed without errors.
        duration_seconds: How long the fetch took in seconds.
    """
    settings = get_settings()
    url = getattr(settings, "notify_webhook_url", None)
    if not url:
        logger.debug("NOTIFY_WEBHOOK_URL not set, skipping notification")
        return

    payload = _build_payload(summary, success, duration_seconds)
    data = json.dumps(payload).encode("utf-8")

    try:
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            logger.info("Notification sent (HTTP %s)", resp.status)
    except urllib.error.URLError as exc:
        logger.warning("Failed to send notification: %s", exc)
    except Exception:
        logger.exception("Unexpected error sending notification")
