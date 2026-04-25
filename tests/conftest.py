"""Shared pytest fixtures."""

from __future__ import annotations

import pytest


@pytest.fixture
def sample_bars() -> list[dict]:
    """A minimal set of OHLCV bar dicts for unit tests."""
    from datetime import datetime, timezone

    return [
        {
            "ts": datetime(2024, 1, d, 9, 0, tzinfo=timezone.utc),
            "open": 18000.0 + d * 10,
            "high": 18050.0 + d * 10,
            "low": 17950.0 + d * 10,
            "close": 18020.0 + d * 10,
            "volume": 1000 * d,
        }
        for d in range(1, 6)
    ]
