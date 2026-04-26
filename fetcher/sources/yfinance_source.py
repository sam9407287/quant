"""yfinance-based market data source for daily ingestion.

yfinance provides free, CME-sourced futures data via Yahoo Finance.
This adapter translates the yfinance API into the standard DataSource
interface used by the pipeline layer.

Known limitation: 1m bars are only available for the past 7 days.
The fetcher compensates by using a configurable overlap window so that
consecutive daily runs never leave a gap.
"""

from __future__ import annotations

import logging
from datetime import datetime

import pandas as pd
import yfinance as yf

from fetcher.sources.base import DataSource

logger = logging.getLogger(__name__)

# Maps our internal symbol to the yfinance continuous-contract ticker
_TICKER_MAP: dict[str, str] = {
    "NQ": "NQ=F",
    "ES": "ES=F",
    "YM": "YM=F",
    "RTY": "RTY=F",
}

# Maps timeframe strings to yfinance interval parameter
_INTERVAL_MAP: dict[str, str] = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "1h": "60m",
    "4h": "1h",    # yfinance does not offer 4h; caller must aggregate
    "1d": "1d",
    "1wk": "1wk",
}


class YFinanceSource(DataSource):
    """Fetch OHLCV bars from Yahoo Finance via the yfinance library."""

    @property
    def source_name(self) -> str:
        return "yfinance"

    def fetch(
        self,
        instrument: str,
        start: datetime,
        end: datetime,
        timeframe: str = "1m",
    ) -> pd.DataFrame:
        """Download OHLCV bars from yfinance and return a normalised DataFrame.

        Args:
            instrument: Internal symbol, e.g. 'NQ'. Must be in _TICKER_MAP.
            start:      Inclusive range start (UTC-aware or naive).
            end:        Exclusive range end (UTC-aware or naive).
            timeframe:  Bar width string from _INTERVAL_MAP keys.

        Returns:
            DataFrame[ts, open, high, low, close, volume] with UTC-aware ts,
            or empty DataFrame if download fails or returns no data.
        """
        ticker = _TICKER_MAP.get(instrument.upper())
        if ticker is None:
            logger.error("Unknown instrument %r; no yfinance ticker mapped", instrument)
            return self._empty_df()

        interval = _INTERVAL_MAP.get(timeframe)
        if interval is None:
            logger.error("Unsupported timeframe %r for yfinance", timeframe)
            return self._empty_df()

        logger.debug(
            "Fetching %s (%s) %s → %s at %s", instrument, ticker, start, end, timeframe
        )

        try:
            raw: pd.DataFrame = yf.download(
                ticker,
                start=start,
                end=end,
                interval=interval,
                auto_adjust=True,
                progress=False,
                multi_level_index=False,  # yfinance >= 0.2.43 / 1.x
            )
        except Exception:
            logger.exception("yfinance download failed for %s", instrument)
            return self._empty_df()

        if raw.empty:
            logger.info("No data returned by yfinance for %s %s→%s", instrument, start, end)
            return self._empty_df()

        return self._normalise(raw)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalise(raw: pd.DataFrame) -> pd.DataFrame:
        """Rename yfinance columns to our standard schema."""
        df = raw.copy()
        df.index.name = "ts"
        df = df.reset_index()

        rename_map = {
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
            "Datetime": "ts",
        }
        df = df.rename(columns=rename_map)

        # Keep only required columns (drop Adj Close if present)
        keep = ["ts", "open", "high", "low", "close", "volume"]
        existing = [c for c in keep if c in df.columns]
        df = df[existing]

        # Ensure ts is UTC
        if hasattr(df["ts"], "dt"):
            if df["ts"].dt.tz is None:
                df["ts"] = df["ts"].dt.tz_localize("UTC")
            else:
                df["ts"] = df["ts"].dt.tz_convert("UTC")

        return df.reset_index(drop=True)

    @staticmethod
    def _empty_df() -> pd.DataFrame:
        return pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])
