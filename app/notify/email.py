"""Outbound email for sharing notifications.

Deliberately degrades: with no provider key configured the send is skipped
and logged, so the in-app notification still works and nothing 500s. Set
RESEND_API_KEY and NOTIFY_FROM_EMAIL to turn real delivery on.

Resend is used because it is a single authenticated POST — no SDK, no SMTP
handshake, and `requests` is already a production dependency.
"""

from __future__ import annotations

import logging

import requests

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_ENDPOINT = "https://api.resend.com/emails"
_TIMEOUT_SECONDS = 10


def _send(to: str, subject: str, html: str) -> bool:
    settings = get_settings()
    if not settings.resend_api_key or not settings.notify_from_email:
        logger.info("email skipped (no provider configured): to=%s subject=%s", to, subject)
        return False
    try:
        response = requests.post(
            _ENDPOINT,
            headers={"Authorization": f"Bearer {settings.resend_api_key}"},
            json={
                "from": settings.notify_from_email,
                "to": [to],
                "subject": subject,
                "html": html,
            },
            timeout=_TIMEOUT_SECONDS,
        )
        if response.status_code >= 400:
            logger.error("email provider rejected the send: %s %s", response.status_code, response.text)
            return False
        return True
    except requests.RequestException:
        # A notification must never take the request down with it.
        logger.exception("email send failed: to=%s", to)
        return False


def _shell(body: str, cta_label: str, cta_path: str) -> str:
    base = get_settings().frontend_base_url.rstrip("/")
    link = f"{base}{cta_path}"
    return (
        '<div style="font-family:system-ui,sans-serif;line-height:1.6;color:#18181b">'
        f"{body}"
        f'<p style="margin-top:24px">'
        f'<a href="{link}" style="background:#3987e5;color:#fff;padding:10px 18px;'
        f'border-radius:6px;text-decoration:none;display:inline-block">{cta_label}</a>'
        "</p>"
        '<p style="color:#71717a;font-size:12px;margin-top:24px">'
        "quant.futures — you are receiving this because someone referenced your "
        "account in the strategy sharing settings.</p></div>"
    )


def send_access_requested(*, to: str, requester_email: str, message: str | None) -> bool:
    note = (
        f'<p style="background:#f4f4f5;padding:12px;border-radius:6px">{message}</p>'
        if message
        else ""
    )
    return _send(
        to,
        f"{requester_email} wants to view your strategies",
        _shell(
            f"<p><strong>{requester_email}</strong> has asked to view the strategies "
            "saved under your account.</p>"
            "<p>They would be able to open and back-test them, and copy one into "
            "their own account. They cannot edit or delete yours.</p>" + note,
            "Review the request",
            "/research/strategies",
        ),
    )


def send_access_decided(*, to: str, owner_email: str, granted: bool) -> bool:
    verb = "granted" if granted else "declined"
    return _send(
        to,
        f"{owner_email} {verb} your strategy access request",
        _shell(
            f"<p><strong>{owner_email}</strong> has <strong>{verb}</strong> your "
            "request to view their strategies.</p>"
            + (
                "<p>Their strategies now appear in your list, grouped under their "
                "address.</p>"
                if granted
                else ""
            ),
            "Open strategies",
            "/research/strategies",
        ),
    )
