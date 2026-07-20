"""Binance spot market data source (ADR-007).

Crypto is sourced from Binance rather than Yahoo for two reasons: the
full 1m history is free and complete back to each pair's listing date
(data.binance.vision monthly archives), and using one venue for both
history and daily updates avoids the price seam that appears when an
aggregated quote is spliced onto exchange data.

Two access paths, same normalised output:
  * `fetch()`      — REST /api/v3/klines, used by the daily fetcher.
  * `iter_month()` — public monthly ZIP archives, used by the bulk
                     history loader (scripts/bootstrap_binance.py).

Timestamp units differ between the two and even between archive
vintages (older files are milliseconds, recent ones microseconds), so
every epoch is normalised by digit count rather than assumed.
"""

from __future__ import annotations

import csv
import io
import logging
import zipfile
from datetime import UTC, datetime

import pandas as pd
import requests

from app.core.instruments import get_binance_pair
from fetcher.sources.base import DataSource

logger = logging.getLogger(__name__)

_API_URL = "https://api.binance.com/api/v3/klines"
_ARCHIVE_URL = (
    "https://data.binance.vision/data/spot/monthly/klines/"
    "{pair}/{tf}/{pair}-{tf}-{year:04d}-{month:02d}.zip"
)
_MAX_LIMIT = 1000  # Binance caps a single klines response at 1000 bars

_INTERVAL_MAP: dict[str, str] = {
    "1m": "1m", "5m": "5m", "15m": "15m",
    "1h": "1h", "4h": "4h", "1d": "1d", "1w": "1w",
}

_COLUMNS = ["ts", "open", "high", "low", "close", "volume"]


def _epoch_to_utc(raw: int | str) -> datetime:
    """Convert a Binance epoch to UTC, detecting ms vs µs by magnitude.

    Archives switched from millisecond to microsecond stamps in 2025;
    both shapes appear in the historical corpus.
    """
    value = int(raw)
    if value > 1_000_000_000_000_000:  # 16 digits → microseconds
        return datetime.fromtimestamp(value / 1_000_000, tz=UTC)
    return datetime.fromtimestamp(value / 1_000, tz=UTC)


def _frame(rows: list[tuple[datetime, float, float, float, float, float]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=_COLUMNS)
    df = pd.DataFrame(rows, columns=_COLUMNS)
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df


class BinanceSource(DataSource):
    """Fetch OHLCV bars from Binance spot markets."""

    @property
    def source_name(self) -> str:
        return "binance"

    def fetch(
        self,
        instrument: str,
        start: datetime,
        end: datetime,
        timeframe: str = "1m",
    ) -> pd.DataFrame:
        """Fetch bars via the REST API, paging through the 1000-bar cap."""
        pair = get_binance_pair(instrument)
        if pair is None:
            logger.error("No Binance pair mapped for %r", instrument)
            return pd.DataFrame(columns=_COLUMNS)
        interval = _INTERVAL_MAP.get(timeframe)
        if interval is None:
            raise ValueError(f"unsupported timeframe for Binance: {timeframe}")

        cursor_ms = int(start.timestamp() * 1000)
        end_ms = int(end.timestamp() * 1000)
        rows: list[tuple[datetime, float, float, float, float, float]] = []

        while cursor_ms < end_ms:
            params: dict[str, str | int] = {
                "symbol": pair,
                "interval": interval,
                "startTime": cursor_ms,
                "endTime": end_ms,
                "limit": _MAX_LIMIT,
            }
            resp = requests.get(_API_URL, params=params, timeout=30)
            resp.raise_for_status()
            batch = resp.json()
            if not batch:
                break
            for k in batch:
                rows.append(
                    (
                        _epoch_to_utc(k[0]),
                        float(k[1]), float(k[2]), float(k[3]), float(k[4]),
                        float(k[5]),
                    )
                )
            # Advance past the last bar's open time; a short batch means
            # we have reached the end of available data.
            cursor_ms = int(batch[-1][0]) + 1
            if len(batch) < _MAX_LIMIT:
                break

        logger.info("Binance %s (%s): %d bars", instrument, pair, len(rows))
        return _frame(rows)

    def iter_month(
        self, instrument: str, year: int, month: int, timeframe: str = "1m"
    ) -> pd.DataFrame:
        """Download one monthly archive; empty frame when it doesn't exist.

        A 404 is normal and expected — it simply means the pair was not
        listed yet in that month.
        """
        pair = get_binance_pair(instrument)
        if pair is None:
            return pd.DataFrame(columns=_COLUMNS)
        url = _ARCHIVE_URL.format(pair=pair, tf=timeframe, year=year, month=month)
        resp = requests.get(url, timeout=120)
        if resp.status_code == 404:
            return pd.DataFrame(columns=_COLUMNS)
        resp.raise_for_status()

        rows: list[tuple[datetime, float, float, float, float, float]] = []
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            name = zf.namelist()[0]
            with zf.open(name) as fh:
                text = io.TextIOWrapper(fh, encoding="utf-8")
                for record in csv.reader(text):
                    if not record or record[0].startswith("open_time"):
                        continue  # some vintages carry a header row
                    rows.append(
                        (
                            _epoch_to_utc(record[0]),
                            float(record[1]), float(record[2]), float(record[3]),
                            float(record[4]), float(record[5]),
                        )
                    )
        return _frame(rows)
