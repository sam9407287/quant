"""Abstract base class for market data sources."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

import pandas as pd


class DataSource(ABC):
    """Interface every data source adapter must implement.

    Concrete implementations hide the specifics of each provider
    (yfinance, IBKR, FirstRate CSV, etc.) behind a uniform API so
    the pipeline layer never depends on a particular vendor.
    """

    @abstractmethod
    def fetch(
        self,
        instrument: str,
        start: datetime,
        end: datetime,
        timeframe: str = "1m",
    ) -> pd.DataFrame:
        """Fetch OHLCV bars for the given instrument and date range.

        Args:
            instrument: Symbol without exchange suffix, e.g. 'NQ', 'ES'.
            start:      Inclusive start of the requested range (UTC).
            end:        Exclusive end of the requested range (UTC).
            timeframe:  Bar width string, e.g. '1m', '5m', '1h'.

        Returns:
            DataFrame with columns [ts, open, high, low, close, volume]
            where ts is timezone-aware UTC DatetimeTZDtype.
            Returns empty DataFrame when no data is available.
        """

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Human-readable identifier stored in kbars_1m.source."""
