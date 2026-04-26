"""Unit tests for YFinanceSource — all network calls are mocked."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from fetcher.sources.yfinance_source import YFinanceSource

START = datetime(2024, 4, 1, 0, 0, tzinfo=UTC)
END = datetime(2024, 4, 2, 0, 0, tzinfo=UTC)


def _make_yf_response(rows: int = 3) -> pd.DataFrame:
    """Build a minimal DataFrame in yfinance's output format."""
    index = pd.date_range("2024-04-01 09:00", periods=rows, freq="1min", tz="America/New_York")
    return pd.DataFrame(
        {
            "Open": [18000.0 + i * 10 for i in range(rows)],
            "High": [18050.0 + i * 10 for i in range(rows)],
            "Low": [17950.0 + i * 10 for i in range(rows)],
            "Close": [18020.0 + i * 10 for i in range(rows)],
            "Volume": [1000 + i * 100 for i in range(rows)],
        },
        index=index,
    )


@pytest.fixture
def source() -> YFinanceSource:
    return YFinanceSource()


class TestYFinanceSourceName:
    def test_source_name(self, source: YFinanceSource) -> None:
        assert source.source_name == "yfinance"


class TestFetch:
    @patch("fetcher.sources.yfinance_source.yf.download")
    def test_returns_normalised_dataframe(
        self, mock_dl: MagicMock, source: YFinanceSource
    ) -> None:
        mock_dl.return_value = _make_yf_response(3)
        df = source.fetch("NQ", START, END)
        assert list(df.columns) == ["ts", "open", "high", "low", "close", "volume"]
        assert len(df) == 3

    @patch("fetcher.sources.yfinance_source.yf.download")
    def test_ts_column_is_utc(
        self, mock_dl: MagicMock, source: YFinanceSource
    ) -> None:
        mock_dl.return_value = _make_yf_response(2)
        df = source.fetch("NQ", START, END)
        assert str(df["ts"].dt.tz) == "UTC"

    @patch("fetcher.sources.yfinance_source.yf.download")
    def test_unknown_instrument_returns_empty(
        self, mock_dl: MagicMock, source: YFinanceSource
    ) -> None:
        df = source.fetch("XX", START, END)
        assert df.empty
        mock_dl.assert_not_called()

    @patch("fetcher.sources.yfinance_source.yf.download")
    def test_unsupported_timeframe_returns_empty(
        self, mock_dl: MagicMock, source: YFinanceSource
    ) -> None:
        df = source.fetch("NQ", START, END, timeframe="3m")
        assert df.empty
        mock_dl.assert_not_called()

    @patch("fetcher.sources.yfinance_source.yf.download")
    def test_empty_yfinance_response_returns_empty(
        self, mock_dl: MagicMock, source: YFinanceSource
    ) -> None:
        mock_dl.return_value = pd.DataFrame()
        df = source.fetch("NQ", START, END)
        assert df.empty

    @patch("fetcher.sources.yfinance_source.yf.download")
    def test_yfinance_exception_returns_empty(
        self, mock_dl: MagicMock, source: YFinanceSource
    ) -> None:
        mock_dl.side_effect = RuntimeError("network error")
        df = source.fetch("NQ", START, END)
        assert df.empty

    @patch("fetcher.sources.yfinance_source.yf.download")
    def test_uses_correct_ticker(
        self, mock_dl: MagicMock, source: YFinanceSource
    ) -> None:
        mock_dl.return_value = _make_yf_response(1)
        source.fetch("ES", START, END)
        call_args = mock_dl.call_args
        assert call_args[0][0] == "ES=F"

    @patch("fetcher.sources.yfinance_source.yf.download")
    def test_all_instruments_mapped(
        self, mock_dl: MagicMock, source: YFinanceSource
    ) -> None:
        mock_dl.return_value = _make_yf_response(1)
        for symbol in ["NQ", "ES", "YM", "RTY"]:
            df = source.fetch(symbol, START, END)
            assert not df.empty, f"{symbol} returned empty DataFrame"

    @patch("fetcher.sources.yfinance_source.yf.download")
    def test_case_insensitive_instrument(
        self, mock_dl: MagicMock, source: YFinanceSource
    ) -> None:
        mock_dl.return_value = _make_yf_response(1)
        df = source.fetch("nq", START, END)
        assert not df.empty
