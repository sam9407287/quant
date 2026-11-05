"""Discord payloads for pairs events, and the one function that posts them.

Formatting is pure (testable); `post` is the only side effect and never
raises — a notification failure must not fail the job that produced it.
The webhook is a separate channel from the ops summary
(`PAIRS_WEBHOOK_URL` vs `NOTIFY_WEBHOOK_URL`) so trade alerts are never
buried under fetch statistics.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from datetime import date
from typing import Any

from app.pairs.schemas import PairStatsModel

logger = logging.getLogger(__name__)

_COLOURS = {
    "entry": 0x2ECC71,
    "exit": 0x3498DB,
    "stop": 0xE74C3C,
    "time_stop": 0xE67E22,
    "breakdown": 0xF1C40F,
    "error": 0xE74C3C,
    "digest": 0x95A5A6,
}
_ICONS = {"entry": "🟢", "exit": "🔵", "stop": "🔴", "time_stop": "🟠", "breakdown": "⚠️", "error": "❌"}


def _fmt(v: float | None, digits: int = 2, suffix: str = "") -> str:
    return "n/a" if v is None else f"{v:.{digits}f}{suffix}"


def analysis_link(base_url: str, y: str, x: str) -> str:
    return f"{base_url.rstrip('/')}/research/pairs/analyze?y={y}&x={x}"


def entry_embed(
    *, signal_date: date, stats: PairStatsModel, side: str, sizing: dict[str, Any] | None, base_url: str
) -> dict[str, Any]:
    """Embed for a new position: what, why, how big, and the 2σ risk."""
    direction = "LONG spread (buy Y / sell X)" if side == "long_spread" else "SHORT spread (sell Y / buy X)"
    lines = [
        f"z = **{_fmt(stats.z)}** · β = {_fmt(stats.beta, 3)} · HL = {_fmt(stats.half_life, 1, 'd')} · EG p = {_fmt(stats.eg_pvalue, 3)}",
        f"stability = {_fmt(stats.stability_ratio, 2)} · Johansen {'✓' if stats.johansen_pass else '✗'} · q = {_fmt(stats.eg_qvalue, 3)}",
    ]
    if sizing:
        lines.append(
            f"size: {sizing.get('y_qty')} {sizing.get('y_contract')} / {sizing.get('x_qty')} {sizing.get('x_contract')}"
            f" (rounding {_fmt(sizing.get('rounding_error_pct'), 1, '%')})"
        )
        if sizing.get("adverse_2sigma_usd") is not None:
            lines.append(f"2σ adverse move ≈ ${sizing['adverse_2sigma_usd']:,.0f}")
    return _embed("entry", f"{stats.pair_name} — {direction}", signal_date, "\n".join(lines), base_url, stats)


def exit_embed(
    *, signal_date: date, stats: PairStatsModel, event: str, side_before: str, days_held: int, base_url: str
) -> dict[str, Any]:
    reason = {
        "exit": "target reached", "stop": "z stop hit", "time_stop": "time stop (3 × HL)",
        "breakdown": "relationship broke down (EG p > threshold for consecutive days)",
    }.get(event, event)
    body = (
        f"close {side_before.replace('_', ' ')} · {reason}\n"
        f"z = **{_fmt(stats.z)}** · held {days_held}d · EG p = {_fmt(stats.eg_pvalue, 3)}"
    )
    return _embed(event, f"{stats.pair_name} — {event.replace('_', ' ').upper()}", signal_date, body, base_url, stats)


def digest_embed(*, signal_date: date, rows: list[PairStatsModel], base_url: str) -> dict[str, Any]:
    """One line per watchlist pair: z, qualification, and the live gate reasons."""
    lines = []
    for r in sorted(rows, key=lambda r: -abs(r.z or 0.0)):
        mark = "✅" if r.qualified else "·"
        lines.append(f"{mark} `{r.pair_name:<9}` z {_fmt(r.z):>6} · p {_fmt(r.eg_pvalue, 3)} · HL {_fmt(r.half_life, 0)}")
    body = "\n".join(lines) if lines else "no pairs scanned"
    return {
        "content": None,
        "embeds": [
            {
                "title": f"📊 Pairs digest — {signal_date.isoformat()}",
                "description": body[:3900],
                "color": _COLOURS["digest"],
                "url": f"{base_url.rstrip('/')}/research/pairs",
            }
        ],
    }


def error_embed(*, signal_date: date, message: str) -> dict[str, Any]:
    return {
        "content": None,
        "embeds": [
            {
                "title": f"❌ Pairs job failed — {signal_date.isoformat()}",
                "description": message[:3900],
                "color": _COLOURS["error"],
            }
        ],
    }


def _embed(event: str, title: str, signal_date: date, body: str, base_url: str, stats: PairStatsModel) -> dict[str, Any]:
    return {
        "content": None,
        "embeds": [
            {
                "title": f"{_ICONS.get(event, '•')} {title}",
                "description": body,
                "color": _COLOURS.get(event, 0x95A5A6),
                "url": analysis_link(base_url, stats.y_ticker, stats.x_ticker),
                "footer": {"text": f"signal date {signal_date.isoformat()} · research only, not an order"},
            }
        ],
    }


def post(url: str, payload: dict[str, Any], *, timeout: float = 10.0) -> bool:
    """POST one payload to a Discord-compatible webhook; False on any failure."""
    if not url:
        return False
    data = json.dumps(payload).encode("utf-8")
    try:
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            ok = bool(200 <= resp.status < 300)
            if not ok:
                logger.warning("pairs webhook answered HTTP %s", resp.status)
            return ok
    except urllib.error.URLError as exc:
        logger.warning("pairs webhook failed: %s", exc)
    except Exception:
        logger.exception("unexpected error posting pairs webhook")
    return False
